from typing import Any

from app.chat.models import ChatMessage
from app.chat.notifications import create_status_notification
from app.core.enums import ChatMessageType, ChatSide, NotificationType, OrderStatus
from app.orders.models import Order
from app.users.models import User


async def _create_user(email: str = "user@test.com") -> User:
    return await User.create(
        email=email,
        hashed_password="x",
        phone="+79991234567",
        name="Иван",
        surname="Иванов",
    )


async def _create_order(requester: User) -> Order:
    from app.listings.models import Listing, ListingCategory

    cat = await ListingCategory.create(name="Test", verified=True)
    org = await _create_org()
    listing = await Listing.create(
        name="Test Listing",
        category=cat,
        organization=org,
        added_by=requester,
        price=1000,
        status="published",
    )
    return await Order.create(
        id="TSTORD",
        listing=listing,
        organization=org,
        requester=requester,
        requested_start_date="2026-04-10",
        requested_end_date="2026-04-15",
        estimated_cost=5000,
    )


async def _create_org() -> Any:
    from app.organizations.models import Organization

    return await Organization.create(
        full_name="Test Org LLC",
        short_name="TestOrg",
        inn="7707083893",
        status="verified",
    )


class TestCreateStatusNotification:
    async def test_creates_two_messages(self) -> None:
        user = await _create_user()
        order = await _create_order(user)
        msgs = await create_status_notification(
            order_id=order.id,
            old_status=OrderStatus.PENDING,
            new_status=OrderStatus.OFFERED,
        )
        assert len(msgs) == 2

    async def test_one_per_side(self) -> None:
        user = await _create_user()
        order = await _create_order(user)
        msgs = await create_status_notification(
            order_id=order.id,
            old_status=OrderStatus.PENDING,
            new_status=OrderStatus.OFFERED,
        )
        sides = {m.recipient_side for m in msgs}
        assert sides == {ChatSide.REQUESTER, ChatSide.ORGANIZATION}

    async def test_notification_fields(self) -> None:
        user = await _create_user()
        order = await _create_order(user)
        msgs = await create_status_notification(
            order_id=order.id,
            old_status=OrderStatus.OFFERED,
            new_status=OrderStatus.ACCEPTED,
        )
        for msg in msgs:
            assert msg.message_type == ChatMessageType.NOTIFICATION
            assert msg.notification_type == NotificationType.STATUS_CHANGED
            assert msg.notification_body == {"old_status": "offered", "new_status": "accepted"}
            assert msg.sender_id is None
            assert msg.text is None
            assert msg.media == []

    async def test_messages_persisted_in_db(self) -> None:
        user = await _create_user()
        order = await _create_order(user)
        await create_status_notification(
            order_id=order.id,
            old_status=OrderStatus.PENDING,
            new_status=OrderStatus.OFFERED,
        )
        count = await ChatMessage.filter(
            order_id=order.id,
            message_type=ChatMessageType.NOTIFICATION,
        ).count()
        assert count == 2


from httpx import AsyncClient  # noqa: E402


class TestNotificationsOnTransition:
    """Verify that order transitions create notification messages."""

    async def test_offer_creates_notifications(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Offering an order creates two notification messages."""
        order_id, _org_id, _org_token, _renter_token = create_order_for_chat
        # create_order_for_chat already creates a PENDING order then offers it.
        # The offer transition (pending→offered) should have created notifications.
        notifications = await ChatMessage.filter(
            order_id=order_id,
            message_type=ChatMessageType.NOTIFICATION,
        )
        assert len(notifications) == 2
        sides = {n.recipient_side for n in notifications}
        assert sides == {ChatSide.REQUESTER, ChatSide.ORGANIZATION}
        for n in notifications:
            assert n.notification_body["new_status"] == "offered"
