import asyncio
import json
import logging
import time
from collections.abc import Coroutine
from typing import Any, cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio.client import PubSub

from app.chat import service
from app.chat.pubsub import publish, subscribe
from app.core.config import get_settings
from app.core.enums import MembershipRole, MembershipStatus, UserRole
from app.core.security import decode_access_token
from app.orders.models import Order
from app.organizations.models import Membership
from app.users.models import User

logger = logging.getLogger(__name__)

ws_router = APIRouter()


# --- Rate Limiter ---


class RateLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._window_start = time.monotonic()
        self._count = 0

    def allow(self) -> bool:
        now = time.monotonic()
        if now - self._window_start >= 60:
            self._window_start = now
            self._count = 0
        if self._count >= self._max:
            return False
        self._count += 1
        return True


# --- Connection Registry ---


_connections: dict[str, set[tuple[str, WebSocket]]] = {}


def _add_connection(order_id: str, user_id: str, ws: WebSocket) -> None:
    if order_id not in _connections:
        _connections[order_id] = set()
    _connections[order_id].add((user_id, ws))


def _remove_connection(order_id: str, user_id: str, ws: WebSocket) -> None:
    conns = _connections.get(order_id)
    if conns:
        conns.discard((user_id, ws))
        if not conns:
            del _connections[order_id]


# --- Auth Helpers ---


async def _authenticate_ws(token: str | None) -> User | None:
    if token is None:
        return None
    try:
        subject = decode_access_token(token)
    except ValueError:
        return None
    user = await User.get_or_none(id=subject)
    if user is None or user.role == UserRole.SUSPENDED:
        return None
    return user


async def _is_chat_participant(user: User, order: Order) -> bool:
    if order.requester_id == user.id:
        return True
    membership = await Membership.get_or_none(
        organization_id=order.organization_id,
        user=user,
        status=MembershipStatus.MEMBER,
        role__in=[MembershipRole.ADMIN, MembershipRole.EDITOR],
    )
    return membership is not None


def _get_side(user: User, order: Order) -> str:
    return "requester" if user.id == order.requester_id else "organization"


# --- Redis Listener ---


async def _listen_redis(pubsub: PubSub, ws: WebSocket, user_id: str) -> None:
    async for raw_message in pubsub.listen():
        if raw_message["type"] != "message":
            continue
        payload: dict[str, Any] = json.loads(raw_message["data"])
        sender_id = payload.pop("_sender_id", None)
        msg_type = payload.get("type")
        # Don't echo typing/read back to the sender
        if msg_type in ("typing", "read") and sender_id == user_id:
            continue
        await ws.send_json(payload)


# --- Client Listener ---


async def _listen_client(
    ws: WebSocket,
    order: Order,
    user: User,
    rate_limiter: RateLimiter,
    *,
    chat_active: bool,
) -> None:
    while True:
        raw = await ws.receive_text()
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_json({"type": "error", "data": {"code": "invalid_json", "detail": "Invalid JSON"}})
            continue

        msg_type = data.get("type")

        if msg_type == "message":
            if not chat_active:
                await ws.send_json(
                    {
                        "type": "error",
                        "data": {"code": "read_only", "detail": "Chat is read-only"},
                    }
                )
                continue
            if not rate_limiter.allow():
                await ws.send_json(
                    {
                        "type": "error",
                        "data": {"code": "rate_limited", "detail": "Too many messages, slow down"},
                    }
                )
                continue
            try:
                message_read = await service.send_message(
                    order,
                    user,
                    data.get("text"),
                    data.get("media_ids", []),
                )
            except Exception as exc:  # noqa: BLE001
                await ws.send_json(
                    {
                        "type": "error",
                        "data": {"code": "validation_error", "detail": str(exc)},
                    }
                )
                continue

            broadcast = {
                "type": "message",
                "data": json.loads(message_read.model_dump_json()),
                "_sender_id": user.id,
            }
            await publish(f"chat:{order.id}", broadcast)

            # Enqueue notification job for offline users
            try:
                from app.media.worker import get_arq_pool

                pool = await get_arq_pool()
                await pool.enqueue_job("notify_new_chat_message", order.id, str(message_read.id))
            except Exception:  # noqa: BLE001
                logger.warning("Failed to enqueue chat notification job", exc_info=True)

        elif msg_type == "typing":
            if not chat_active:
                continue
            side = _get_side(user, order)
            await publish(
                f"chat:{order.id}",
                {
                    "type": "typing",
                    "data": {"side": side, "is_typing": bool(data.get("is_typing", False))},
                    "_sender_id": user.id,
                },
            )

        elif msg_type == "read":
            until_id = data.get("until_message_id")
            if not until_id:
                continue
            try:
                await service.mark_messages_read(order.id, user.id, until_id)
            except Exception:  # noqa: BLE001
                logger.warning("Failed to mark messages as read", exc_info=True)
                continue
            side = _get_side(user, order)
            await publish(
                f"chat:{order.id}",
                {
                    "type": "read",
                    "data": {"side": side, "until_message_id": until_id},
                    "_sender_id": user.id,
                },
            )


# --- WebSocket Endpoint ---


@ws_router.websocket("/api/v1/orders/{order_id}/chat/ws")
async def chat_websocket(websocket: WebSocket, order_id: str, token: str | None = None) -> None:
    user = await _authenticate_ws(token)
    if user is None:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    order = await Order.get_or_none(id=order_id)
    if order is None:
        await websocket.close(code=4004, reason="Order not found")
        return

    if not await _is_chat_participant(user, order):
        await websocket.close(code=4003, reason="Not a chat participant")
        return

    await websocket.accept()

    settings = get_settings()
    status_resp = await service.compute_chat_status_for_order(order, user)
    chat_active = status_resp.status == "active"
    await websocket.send_json({"type": "connected", "data": {"chat_status": status_resp.status}})

    _add_connection(order_id, user.id, websocket)
    pubsub = await subscribe(f"chat:{order_id}")
    rate_limiter = RateLimiter(max_per_minute=settings.chat.rate_limit_per_minute)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_listen_redis(pubsub, websocket, user.id))
            tg.create_task(_listen_client(websocket, order, user, rate_limiter, chat_active=chat_active))
    except* WebSocketDisconnect:
        pass
    except* Exception:  # noqa: BLE001
        logger.warning("WebSocket error for order %s", order_id, exc_info=True)
    finally:
        _remove_connection(order_id, user.id, websocket)
        await pubsub.unsubscribe(f"chat:{order_id}")
        await cast("Coroutine[None, None, None]", getattr(pubsub, "aclose")())
