from datetime import UTC, datetime

from tortoise.expressions import Q

from app.chat.models import ChatMessage
from app.core.enums import ChatMessageType, ChatSide, NotificationType, OrderStatus
from app.core.identifiers import generate_short_id
from app.core.security import hash_password
from app.orders.models import Order
from app.organizations.models import Organization
from app.users.models import User


async def _create_user(email: str = "user@test.com") -> User:
    return await User.create(
        id=generate_short_id(),
        email=email,
        hashed_password=hash_password("pass"),
        phone="+79991234567",
        name="Test",
        surname="User",
    )


async def _create_order(requester: User) -> Order:
    org = await Organization.create(
        id=generate_short_id(),
        inn="7707083893",
        short_name="Test Org",
        full_name="Test Organization LLC",
    )
    from app.listings.models import Listing, ListingCategory

    category = await ListingCategory.create(name="Test", verified=True)
    listing = await Listing.create(
        id=generate_short_id(),
        name="Test Listing",
        category=category,
        price=1000.00,
        organization=org,
        added_by=requester,
    )
    return await Order.create(
        id=generate_short_id(),
        listing=listing,
        organization=org,
        requester=requester,
        requested_start_date=datetime(2026, 5, 1, tzinfo=UTC).date(),
        requested_end_date=datetime(2026, 5, 10, tzinfo=UTC).date(),
        status=OrderStatus.PENDING,
    )


class TestChatMessageCRUD:
    async def test_create_text_message(self) -> None:
        user = await _create_user()
        order = await _create_order(user)

        msg = await ChatMessage.create(
            order=order,
            sender=user,
            text="Hello",
        )

        assert msg.id is not None
        assert msg.order_id == order.id
        assert msg.sender_id == user.id
        assert msg.text == "Hello"
        assert msg.media == []
        assert msg.read_at is None
        assert msg.created_at is not None

    async def test_create_media_only_message(self) -> None:
        user = await _create_user()
        order = await _create_order(user)

        snapshots = [{"id": "abc", "kind": "photo", "variants": {"large": "media/abc/large.webp"}}]
        msg = await ChatMessage.create(
            order=order,
            sender=user,
            media=snapshots,
        )

        assert msg.text is None
        assert msg.media == snapshots

    async def test_mark_as_read(self) -> None:
        user = await _create_user()
        order = await _create_order(user)

        msg = await ChatMessage.create(order=order, sender=user, text="Hello")
        assert msg.read_at is None

        now = datetime.now(tz=UTC)
        msg.read_at = now
        await msg.save()

        refreshed = await ChatMessage.get(id=msg.id)
        assert refreshed.read_at is not None

    async def test_ordering_newest_first(self) -> None:
        user = await _create_user()
        order = await _create_order(user)

        msg1 = await ChatMessage.create(order=order, sender=user, text="First")
        msg2 = await ChatMessage.create(order=order, sender=user, text="Second")

        messages = await ChatMessage.filter(order=order).all()
        assert messages[0].id == msg2.id
        assert messages[1].id == msg1.id

    async def test_create_notification_message(self) -> None:
        user = await _create_user()
        order = await _create_order(user)
        msg = await ChatMessage.create(
            order=order,
            sender=None,
            message_type=ChatMessageType.NOTIFICATION,
            notification_type=NotificationType.STATUS_CHANGED,
            recipient_side=ChatSide.REQUESTER,
            notification_body={"old_status": "pending", "new_status": "offered"},
            text=None,
            media=[],
        )
        assert msg.sender_id is None
        assert msg.message_type == ChatMessageType.NOTIFICATION
        assert msg.notification_type == NotificationType.STATUS_CHANGED
        assert msg.recipient_side == ChatSide.REQUESTER
        assert msg.notification_body == {"old_status": "pending", "new_status": "offered"}
        assert msg.text is None

    async def test_cascade_delete_with_order(self) -> None:
        user = await _create_user()
        order = await _create_order(user)
        await ChatMessage.create(order=order, sender=user, text="Hello")

        assert await ChatMessage.filter(order=order).count() == 1
        await order.delete()
        assert await ChatMessage.filter(order_id=order.id).count() == 0

    async def test_get_messages_filters_by_side(self) -> None:
        """Notification messages are only visible to their recipient side."""
        user = await _create_user("side_filter@test.com")
        order = await _create_order(user)

        # Regular message (visible to both)
        await ChatMessage.create(order=order, sender=user, text="Hello", media=[])

        # Notification for requester only
        await ChatMessage.create(
            order=order,
            sender=None,
            message_type=ChatMessageType.NOTIFICATION,
            notification_type=NotificationType.STATUS_CHANGED,
            recipient_side=ChatSide.REQUESTER,
            notification_body={"old_status": "pending", "new_status": "offered"},
            text=None,
            media=[],
        )

        # Notification for organization only
        await ChatMessage.create(
            order=order,
            sender=None,
            message_type=ChatMessageType.NOTIFICATION,
            notification_type=NotificationType.STATUS_CHANGED,
            recipient_side=ChatSide.ORGANIZATION,
            notification_body={"old_status": "pending", "new_status": "offered"},
            text=None,
            media=[],
        )

        # Requester sees regular + their notification = 2
        requester_msgs = await ChatMessage.filter(
            Q(order_id=order.id) & (Q(recipient_side__isnull=True) | Q(recipient_side=ChatSide.REQUESTER))
        )
        assert len(requester_msgs) == 2

        # Organization sees regular + their notification = 2
        org_msgs = await ChatMessage.filter(
            Q(order_id=order.id) & (Q(recipient_side__isnull=True) | Q(recipient_side=ChatSide.ORGANIZATION))
        )
        assert len(org_msgs) == 2
