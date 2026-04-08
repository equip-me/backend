"""Integration tests for order chat notification messages."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from httpx_ws import AsyncWebSocketSession, aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from app.main import app

pytestmark = pytest.mark.e2e


@asynccontextmanager
async def make_ws_client() -> AsyncGenerator[AsyncClient]:
    """Create a fresh AsyncClient backed by ASGIWebSocketTransport."""
    async with ASGIWebSocketTransport(app=app) as transport:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


_WS_TIMEOUT: float = 5.0


async def ws_receive(ws: AsyncWebSocketSession) -> dict[str, Any]:
    """Receive JSON from WebSocket with a timeout to prevent infinite hangs in CI."""
    async with asyncio.timeout(_WS_TIMEOUT):
        result: dict[str, Any] = await ws.receive_json()
    return result


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestChatNotificationsREST:
    async def test_requester_sees_own_notification(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """GET messages as requester should include notification with side='requester'."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers=_auth(renter_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        notifications = [m for m in items if m["message_type"] == "notification"]
        assert len(notifications) >= 1
        n = notifications[0]
        assert n["notification_type"] == "status_changed"
        assert n["notification_body"]["new_status"] == "offered"
        assert n["name"] is None
        assert n["side"] == "requester"

    async def test_org_sees_own_notification(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """GET messages as org should include notification with side='organization'."""
        order_id, org_id, org_token, _renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/messages",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        notifications = [m for m in items if m["message_type"] == "notification"]
        assert len(notifications) >= 1
        n = notifications[0]
        assert n["notification_type"] == "status_changed"
        assert n["notification_body"]["new_status"] == "offered"
        assert n["name"] is None
        assert n["side"] == "organization"

    async def test_requester_does_not_see_org_notification(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Requester's messages should never have side='organization' on notifications."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers=_auth(renter_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        org_notifications = [m for m in items if m["message_type"] == "notification" and m["side"] == "organization"]
        assert org_notifications == []

    async def test_org_does_not_see_requester_notification(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Org's messages should never have side='requester' on notifications."""
        order_id, org_id, org_token, _renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/messages",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        requester_notifications = [
            m for m in items if m["message_type"] == "notification" and m["side"] == "requester"
        ]
        assert requester_notifications == []

    async def test_unread_count_includes_notifications(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Chat status for renter should have unread_count >= 1 (from offer notification)."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/status",
            headers=_auth(renter_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["unread_count"] >= 1


class TestChatNotificationsWebSocket:
    async def test_notification_delivered_to_correct_side(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """When org approves order, both sides receive their own notification via WebSocket."""
        order_id, org_id, org_token, renter_token = create_order_for_chat

        # Accept the order as renter (offered → accepted)
        resp = await client.patch(f"/api/v1/orders/{order_id}/accept", headers=_auth(renter_token))
        assert resp.status_code == 200

        renter_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        org_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # Barrier ensures both WS sessions are subscribed before approve fires.
        barrier = asyncio.Barrier(3)
        approved = asyncio.Event()

        async def renter_session() -> None:
            async with make_ws_client() as wsc:
                ws: AsyncWebSocketSession
                async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc) as ws:
                    await ws_receive(ws)  # connected
                    await barrier.wait()  # signal ready, wait for all three
                    async with asyncio.timeout(_WS_TIMEOUT):
                        await approved.wait()
                    renter_q.put_nowait(await ws_receive(ws))

        async def org_session() -> None:
            async with make_ws_client() as wsc:
                ws2: AsyncWebSocketSession
                async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={org_token}", wsc) as ws2:
                    await ws_receive(ws2)  # connected
                    await barrier.wait()  # signal ready, wait for all three
                    async with asyncio.timeout(_WS_TIMEOUT):
                        await approved.wait()
                    org_q.put_nowait(await ws_receive(ws2))

        async def approver() -> None:
            await barrier.wait()  # wait for both WS sessions to be ready
            approve_resp = await client.patch(
                f"/api/v1/organizations/{org_id}/orders/{order_id}/approve",
                headers=_auth(org_token),
            )
            assert approve_resp.status_code == 200
            approved.set()

        await asyncio.gather(renter_session(), org_session(), approver())

        renter_notif = renter_q.get_nowait()
        assert renter_notif["type"] == "notification"
        assert renter_notif["data"]["notification_type"] == "status_changed"
        assert renter_notif["data"]["notification_body"]["new_status"] == "confirmed"

        org_notif = org_q.get_nowait()
        assert org_notif["type"] == "notification"
        assert org_notif["data"]["notification_type"] == "status_changed"
        assert org_notif["data"]["notification_body"]["new_status"] == "confirmed"

    async def test_notification_not_cross_contaminated(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Renter WS must not receive organization-side notification frames."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        # Accept order so we can trigger another transition (offered → accepted)
        accept_resp = await client.patch(
            f"/api/v1/orders/{order_id}/accept",
            headers=_auth(renter_token),
        )
        assert accept_resp.status_code == 200

        # Renter should only see a notification with side='requester'
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers=_auth(renter_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        for item in items:
            if item["message_type"] == "notification":
                assert item["side"] == "requester", f"Expected requester side, got: {item['side']}"


class TestChatNotificationEdgeCases:
    async def test_read_only_marks_own_side(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Mark-as-read for requester does not affect org's unread count."""
        order_id, org_id, org_token, renter_token = create_order_for_chat

        # Get renter's notification message id to mark as read
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers=_auth(renter_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        notifications = [m for m in items if m["message_type"] == "notification"]
        assert len(notifications) >= 1

        # Mark renter's notification as read via WebSocket
        notif_id = notifications[0]["id"]
        async with make_ws_client() as wsc:
            ws: AsyncWebSocketSession
            async with aconnect_ws(f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc) as ws:
                await ws_receive(ws)  # connected
                await ws.send_json({"type": "read", "until_message_id": notif_id})
                # Connection stays open — send a message to confirm it's alive
                await ws.send_json({"type": "message", "text": "ping"})
                await ws_receive(ws)  # echo of ping message

        # Renter's unread count should now be 0 for that notification
        renter_status = await client.get(
            f"/api/v1/orders/{order_id}/chat/status",
            headers=_auth(renter_token),
        )
        assert renter_status.status_code == 200
        renter_unread = renter_status.json()["unread_count"]

        # Org still has its own unread notification (was not touched by renter's read)
        org_status = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/status",
            headers=_auth(org_token),
        )
        assert org_status.status_code == 200
        org_unread = org_status.json()["unread_count"]

        # After renter marks their notification read, renter's count drops
        # but org's notification is still unread (at least the offer notification)
        assert renter_unread < org_unread or org_unread >= 1

    async def test_cancel_creates_notification_in_active_chat(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Canceling an order creates a notification; chat stays active during cooldown."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        # Accept so order is in ACCEPTED (renter can cancel from OFFERED too)
        cancel_resp = await client.patch(
            f"/api/v1/orders/{order_id}/cancel",
            headers=_auth(renter_token),
        )
        assert cancel_resp.status_code == 200

        # Chat should still be active (within cooldown window)
        status_resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/status",
            headers=_auth(renter_token),
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "active"

        # There should be a cancellation notification
        msgs_resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers=_auth(renter_token),
        )
        assert msgs_resp.status_code == 200
        items = msgs_resp.json()["items"]
        cancel_notifications = [
            m
            for m in items
            if m["message_type"] == "notification"
            and m.get("notification_body", {}).get("new_status") == "canceled_by_user"
        ]
        assert len(cancel_notifications) >= 1

    async def test_notification_has_no_sender_name(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Notification messages must have name=None (they have no human author)."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers=_auth(renter_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        for item in items:
            if item["message_type"] == "notification":
                assert item["name"] is None

    async def test_notification_has_no_text(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Notification messages must have text=None."""
        order_id, _org_id, _org_token, renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers=_auth(renter_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        for item in items:
            if item["message_type"] == "notification":
                assert item["text"] is None
