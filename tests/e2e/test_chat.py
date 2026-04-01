import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from httpx_ws import AsyncWebSocketSession, aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from app.core.enums import OrderStatus
from app.main import app
from app.orders.models import Order

pytestmark = pytest.mark.e2e


@asynccontextmanager
async def make_ws_client() -> AsyncGenerator[AsyncClient]:
    """Create a fresh AsyncClient backed by ASGIWebSocketTransport."""
    async with ASGIWebSocketTransport(app=app) as transport:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


class TestChatRESTEndpoints:
    async def test_get_messages_empty(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["has_more"] is False

    async def test_get_chat_status_active(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/status",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["unread_count"] == 0

    async def test_get_messages_not_participant(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
        create_user: Any,
    ) -> None:
        order_id, _org_id, _org_token, _renter_token = create_order_for_chat
        _, outsider_token = await create_user(email="outsider@example.com", phone="+79005555555")
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert resp.status_code == 403

    async def test_get_messages_org_side(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, org_id, org_token, _renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/messages",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_get_org_chat_status(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, org_id, org_token, _renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/status",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"


class TestChatWebSocket:
    async def test_ws_connect_and_receive_connected(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                data = await ws.receive_json()
                assert data["type"] == "connected"
                assert data["data"]["chat_status"] == "active"

    async def test_ws_connect_invalid_token(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        from httpx_ws._exceptions import WebSocketDisconnect

        order_id, _org_id, _org_token, _renter_token = create_order_for_chat
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            with pytest.raises(WebSocketDisconnect) as exc_info:
                async with aconnect_ws(
                    f"/api/v1/orders/{order_id}/chat/ws?token=invalid",
                    wsc,
                ) as ws:
                    await ws.receive_json()
            assert exc_info.value.code == 4001

    async def test_ws_connect_not_participant(
        self,
        create_order_for_chat: tuple[str, str, str, str],
        create_user: Any,
    ) -> None:
        from httpx_ws._exceptions import WebSocketDisconnect

        order_id, _org_id, _org_token, _renter_token = create_order_for_chat
        _, outsider_token = await create_user(email="outsider2@example.com", phone="+79005555556")
        async with make_ws_client() as wsc:
            ws2: AsyncWebSocketSession
            with pytest.raises(WebSocketDisconnect) as exc_info:
                async with aconnect_ws(
                    f"/api/v1/orders/{order_id}/chat/ws?token={outsider_token}",
                    wsc,
                ) as ws2:
                    await ws2.receive_json()
            assert exc_info.value.code == 4003

    async def test_ws_send_and_receive_message(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, org_token, renter_token = create_order_for_chat

        # Use asyncio queues to communicate between tasks running separate WS sessions
        renter_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        org_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        sent = asyncio.Event()

        async def renter_session() -> None:
            async with make_ws_client() as wsc:
                ws: AsyncWebSocketSession
                async with aconnect_ws(
                    f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc
                ) as ws:
                    await ws.receive_json()  # connected
                    await ws.send_json({"type": "message", "text": "Hello org!"})
                    msg = await ws.receive_json()
                    renter_q.put_nowait(msg)
                    sent.set()

        async def org_session() -> None:
            async with make_ws_client() as wsc:
                ws: AsyncWebSocketSession
                async with aconnect_ws(
                    f"/api/v1/orders/{order_id}/chat/ws?token={org_token}", wsc
                ) as ws:
                    await ws.receive_json()  # connected
                    await sent.wait()
                    msg = await ws.receive_json()
                    org_q.put_nowait(msg)

        await asyncio.gather(renter_session(), org_session())

        renter_msg = renter_q.get_nowait()
        assert renter_msg["type"] == "message"
        assert renter_msg["data"]["side"] == "requester"
        assert renter_msg["data"]["text"] == "Hello org!"

        org_msg = org_q.get_nowait()
        assert org_msg["type"] == "message"
        assert org_msg["data"]["side"] == "requester"
        assert org_msg["data"]["text"] == "Hello org!"

    async def test_ws_read_receipt(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, org_token, renter_token = create_order_for_chat

        renter_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        org_q: asyncio.Queue[str] = asyncio.Queue()  # stores msg_id after send
        sent_event = asyncio.Event()
        read_event = asyncio.Event()

        async def renter_session() -> None:
            async with make_ws_client() as wsc:
                ws: AsyncWebSocketSession
                async with aconnect_ws(
                    f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc
                ) as ws:
                    await ws.receive_json()  # connected
                    await ws.send_json({"type": "message", "text": "Read this"})
                    msg = await ws.receive_json()  # own echo
                    org_q.put_nowait(msg["data"]["id"])
                    sent_event.set()
                    await read_event.wait()
                    receipt = await ws.receive_json()
                    renter_q.put_nowait(receipt)

        async def org_session() -> None:
            async with make_ws_client() as wsc:
                ws: AsyncWebSocketSession
                async with aconnect_ws(
                    f"/api/v1/orders/{order_id}/chat/ws?token={org_token}", wsc
                ) as ws:
                    await ws.receive_json()  # connected
                    await sent_event.wait()
                    await ws.receive_json()  # drain the broadcast message
                    msg_id = org_q.get_nowait()
                    await ws.send_json({"type": "read", "until_message_id": msg_id})
                    read_event.set()

        await asyncio.gather(renter_session(), org_session())

        read_receipt = renter_q.get_nowait()

        assert read_receipt["type"] == "read"
        assert read_receipt["data"]["side"] == "organization"
        assert read_receipt["data"]["until_message_id"] is not None

        from app.chat.models import ChatMessage

        db_msg = await ChatMessage.get(id=read_receipt["data"]["until_message_id"])
        assert db_msg.read_at is not None

    async def test_ws_read_only_chat(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        order = await Order.get(id=order_id)
        order.status = OrderStatus.REJECTED
        await order.save()
        from tortoise import connections

        conn = connections.get("default")
        await conn.execute_query(
            "UPDATE orders SET updated_at = updated_at - interval '30 days' WHERE id = $1",
            [order_id],
        )

        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                connected = await ws.receive_json()
                assert connected["data"]["chat_status"] == "read_only"

                await ws.send_json({"type": "message", "text": "Too late"})
                error = await ws.receive_json()
                assert error["type"] == "error"
                assert error["data"]["code"] == "read_only"

    async def test_messages_visible_in_rest_after_ws_send(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()
                await ws.send_json({"type": "message", "text": "Persisted!"})
                await ws.receive_json()

        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["text"] == "Persisted!"
        assert items[0]["side"] == "requester"

    async def test_unread_count(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, org_id, org_token, renter_token = create_order_for_chat

        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()
                await ws.send_json({"type": "message", "text": "Msg 1"})
                await ws.receive_json()
                await ws.send_json({"type": "message", "text": "Msg 2"})
                await ws.receive_json()

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/status",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["unread_count"] == 2

        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/status",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["unread_count"] == 0

    async def test_message_validation_empty(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()
                await ws.send_json({"type": "message"})
                error = await ws.receive_json()
                assert error["type"] == "error"
                assert error["data"]["code"] == "validation_error"

    async def test_message_author_display(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, org_token, renter_token = create_order_for_chat

        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()
                await ws.send_json({"type": "message", "text": "Hi"})
                msg = await ws.receive_json()
                assert msg["data"]["side"] == "requester"
                assert msg["data"]["name"] == "Renter Testov"

        async with make_ws_client() as wsc:
            ws2: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={org_token}",
                wsc,
            ) as ws2:
                await ws2.receive_json()
                await ws2.send_json({"type": "message", "text": "Reply"})
                msg = await ws2.receive_json()
                assert msg["data"]["side"] == "organization"
                assert len(msg["data"]["name"]) > 0
