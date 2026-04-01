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

    async def test_get_messages_order_not_found(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        _order_id, _org_id, _org_token, renter_token = create_order_for_chat
        resp = await client.get(
            "/api/v1/orders/ZZZZZZ/chat/messages",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 404

    async def test_get_messages_org_order_not_found(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, org_token, _renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/organizations/ZZZZZZ/orders/{order_id}/chat/messages",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 404

    async def test_get_messages_org_viewer_forbidden(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
        create_user: Any,
    ) -> None:
        """Org viewer cannot access chat."""
        from app.core.enums import MembershipRole, MembershipStatus
        from app.organizations.models import Membership, Organization
        from app.users.models import User

        order_id, org_id, _org_token, _renter_token = create_order_for_chat
        _, viewer_token = await create_user(email="viewer@example.com", phone="+79005555557")

        viewer_resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {viewer_token}"})
        viewer_id = viewer_resp.json()["id"]
        viewer = await User.get(id=viewer_id)
        org = await Organization.get(id=org_id)
        await Membership.create(
            user=viewer,
            organization=org,
            role=MembershipRole.VIEWER,
            status=MembershipStatus.MEMBER,
        )

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/messages",
            headers={"Authorization": f"Bearer {viewer_token}"},
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
                async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc) as ws:
                    await ws.receive_json()  # connected
                    await ws.send_json({"type": "message", "text": "Hello org!"})
                    msg = await ws.receive_json()
                    renter_q.put_nowait(msg)
                    sent.set()

        async def org_session() -> None:
            async with make_ws_client() as wsc:
                ws: AsyncWebSocketSession
                async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={org_token}", wsc) as ws:
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
                async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc) as ws:
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
                async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={org_token}", wsc) as ws:
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

    async def test_ws_connect_no_token(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """WebSocket without token query param should be rejected."""
        from httpx_ws._exceptions import WebSocketDisconnect

        order_id, _org_id, _org_token, _renter_token = create_order_for_chat
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            with pytest.raises(WebSocketDisconnect) as exc_info:
                async with aconnect_ws(
                    f"/api/v1/orders/{order_id}/chat/ws",
                    wsc,
                ) as ws:
                    await ws.receive_json()
            assert exc_info.value.code == 4001

    async def test_ws_connect_suspended_user(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Suspended user should be rejected."""
        from httpx_ws._exceptions import WebSocketDisconnect

        from app.core.enums import UserRole
        from app.core.security import decode_access_token
        from app.users.models import User

        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        renter_id = decode_access_token(renter_token)
        await User.filter(id=renter_id).update(role=UserRole.SUSPENDED)

        async with make_ws_client() as wsc:
            ws2: AsyncWebSocketSession
            with pytest.raises(WebSocketDisconnect) as exc_info:
                async with aconnect_ws(
                    f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                    wsc,
                ) as ws2:
                    await ws2.receive_json()
            assert exc_info.value.code == 4001

    async def test_ws_connect_order_not_found(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """WebSocket for nonexistent order should get 4004."""
        from httpx_ws._exceptions import WebSocketDisconnect

        _order_id, _org_id, _org_token, renter_token = create_order_for_chat
        async with make_ws_client() as wsc:
            ws3: AsyncWebSocketSession
            with pytest.raises(WebSocketDisconnect) as exc_info:
                async with aconnect_ws(
                    f"/api/v1/orders/ZZZZZZ/chat/ws?token={renter_token}",
                    wsc,
                ) as ws3:
                    await ws3.receive_json()
            assert exc_info.value.code == 4004

    async def test_ws_invalid_json(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Sending invalid JSON should return error frame."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()  # connected
                await ws.send_text("not valid json{{{")
                error = await ws.receive_json()
                assert error["type"] == "error"
                assert error["data"]["code"] == "invalid_json"

    async def test_ws_rate_limiting(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Exceeding rate limit should return error frame."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()  # connected
                # Send messages up to the limit (default 30/min)
                for i in range(30):
                    await ws.send_json({"type": "message", "text": f"Msg {i}"})
                    await ws.receive_json()  # echo
                # Next message should be rate limited
                await ws.send_json({"type": "message", "text": "Over limit"})
                error = await ws.receive_json()
                assert error["type"] == "error"
                assert error["data"]["code"] == "rate_limited"

    async def test_ws_typing_indicator(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Typing indicator should be broadcast to other participant."""
        order_id, _org_id, org_token, renter_token = create_order_for_chat

        org_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        typing_sent = asyncio.Event()

        async def renter_session() -> None:
            async with make_ws_client() as wsc:
                ws: AsyncWebSocketSession
                async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc) as ws:
                    await ws.receive_json()  # connected
                    await ws.send_json({"type": "typing", "is_typing": True})
                    typing_sent.set()
                    # Give time for broadcast
                    await asyncio.sleep(0.5)

        async def org_session() -> None:
            async with make_ws_client() as wsc:
                ws2: AsyncWebSocketSession
                async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={org_token}", wsc) as ws2:
                    await ws2.receive_json()  # connected
                    await typing_sent.wait()
                    msg = await ws2.receive_json()
                    org_q.put_nowait(msg)

        await asyncio.gather(renter_session(), org_session())

        typing_msg = org_q.get_nowait()
        assert typing_msg["type"] == "typing"
        assert typing_msg["data"]["side"] == "requester"
        assert typing_msg["data"]["is_typing"] is True

    async def test_ws_message_text_too_long(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Message exceeding max length should return validation error."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()  # connected
                long_text = "x" * 4001
                await ws.send_json({"type": "message", "text": long_text})
                error = await ws.receive_json()
                assert error["type"] == "error"
                assert error["data"]["code"] == "validation_error"

    async def test_ws_message_with_invalid_media_id(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Message with invalid media UUID should return validation error."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()  # connected
                await ws.send_json({"type": "message", "text": "Hi", "media_ids": ["not-a-uuid"]})
                error = await ws.receive_json()
                assert error["type"] == "error"
                assert error["data"]["code"] == "validation_error"

    async def test_ws_message_with_nonexistent_media(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Message with nonexistent media ID should return error."""
        import uuid

        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()  # connected
                fake_id = str(uuid.uuid4())
                await ws.send_json({"type": "message", "text": "Hi", "media_ids": [fake_id]})
                error = await ws.receive_json()
                assert error["type"] == "error"
                assert error["data"]["code"] == "validation_error"

    async def test_ws_read_missing_message_id(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Read frame without until_message_id should be silently ignored."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()  # connected
                await ws.send_json({"type": "read"})
                # Send a valid message to verify connection is still alive
                await ws.send_json({"type": "message", "text": "Still alive"})
                msg = await ws.receive_json()
                assert msg["type"] == "message"

    async def test_ws_read_nonexistent_message(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Read frame with nonexistent message_id should be handled gracefully."""
        import uuid

        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()  # connected
                await ws.send_json({"type": "read", "until_message_id": str(uuid.uuid4())})
                # Should not crash — send another message to verify
                await ws.send_json({"type": "message", "text": "Still works"})
                msg = await ws.receive_json()
                assert msg["type"] == "message"

    async def test_message_with_media_attachment(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Send message with media attachment. Covers media validation, snapshot, linking, and URL resolution."""
        from uuid import uuid4

        from app.core.enums import MediaContext, MediaKind, MediaOwnerType, MediaStatus
        from app.core.security import decode_access_token
        from app.media.models import Media
        from app.users.models import User

        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        renter_id = decode_access_token(renter_token)
        renter = await User.get(id=renter_id)

        # Create a ready media record directly in DB (bypass S3 upload for test)
        media_id = uuid4()
        await Media.create(
            id=media_id,
            uploaded_by=renter,
            kind=MediaKind.PHOTO,
            context=MediaContext.CHAT,
            status=MediaStatus.READY,
            original_filename="test.jpg",
            content_type="image/jpeg",
            file_size=1024,
            upload_key=f"pending/{media_id}/test.jpg",
            variants={"thumbnail": f"media/{media_id}/thumbnail.webp", "large": f"media/{media_id}/large.webp"},
        )

        # Send message with media via WebSocket
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                wsc,
            ) as ws:
                await ws.receive_json()  # connected
                await ws.send_json({"type": "message", "text": "See photo", "media_ids": [str(media_id)]})
                msg = await ws.receive_json()
                assert msg["type"] == "message"
                assert msg["data"]["text"] == "See photo"
                assert len(msg["data"]["media"]) == 1
                attachment = msg["data"]["media"][0]
                assert attachment["id"] == str(media_id)
                assert attachment["kind"] == "photo"
                assert "thumbnail" in attachment["urls"]
                assert "large" in attachment["urls"]

        # Verify media is linked to message
        media = await Media.get(id=media_id)
        assert media.owner_type == MediaOwnerType.MESSAGE
        assert media.owner_id is not None

        # Verify via REST endpoint (covers _resolve_media_urls in get_messages path)
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert len(items[0]["media"]) == 1
        assert "thumbnail" in items[0]["media"][0]["urls"]

    async def test_message_with_unready_media(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Media that is not ready should be rejected."""
        from uuid import uuid4

        from app.core.enums import MediaContext, MediaKind, MediaStatus
        from app.core.security import decode_access_token
        from app.media.models import Media
        from app.users.models import User

        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        renter_id = decode_access_token(renter_token)
        renter = await User.get(id=renter_id)

        media_id = uuid4()
        await Media.create(
            id=media_id,
            uploaded_by=renter,
            kind=MediaKind.PHOTO,
            context=MediaContext.CHAT,
            status=MediaStatus.PROCESSING,
            original_filename="test.jpg",
            content_type="image/jpeg",
            file_size=1024,
            upload_key=f"pending/{media_id}/test.jpg",
        )

        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc) as ws:
                await ws.receive_json()
                await ws.send_json({"type": "message", "text": "Photo", "media_ids": [str(media_id)]})
                error = await ws.receive_json()
                assert error["type"] == "error"
                assert error["data"]["code"] == "validation_error"

    async def test_message_with_others_media(
        self,
        create_order_for_chat: tuple[str, str, str, str],
        create_user: Any,
    ) -> None:
        """Media uploaded by another user should be rejected."""
        from uuid import uuid4

        from app.core.enums import MediaContext, MediaKind, MediaStatus
        from app.media.models import Media
        from app.users.models import User

        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        # Create media owned by a different user
        other_data, _ = await create_user(email="other@example.com", phone="+79009999999")
        other_user = await User.get(id=other_data["id"])
        media_id = uuid4()
        await Media.create(
            id=media_id,
            uploaded_by=other_user,
            kind=MediaKind.PHOTO,
            context=MediaContext.CHAT,
            status=MediaStatus.READY,
            original_filename="test.jpg",
            content_type="image/jpeg",
            file_size=1024,
            upload_key=f"pending/{media_id}/test.jpg",
            variants={"thumbnail": f"media/{media_id}/thumbnail.webp"},
        )

        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc) as ws:
                await ws.receive_json()
                await ws.send_json({"type": "message", "text": "Stolen", "media_ids": [str(media_id)]})
                error = await ws.receive_json()
                assert error["type"] == "error"
                assert error["data"]["code"] == "validation_error"

    async def test_message_too_many_attachments(
        self,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """More than 10 attachments should be rejected."""
        import uuid

        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        fake_ids = [str(uuid.uuid4()) for _ in range(11)]
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc) as ws:
                await ws.receive_json()
                await ws.send_json({"type": "message", "text": "Too many", "media_ids": fake_ids})
                error = await ws.receive_json()
                assert error["type"] == "error"
                assert error["data"]["code"] == "validation_error"
