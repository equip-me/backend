from datetime import UTC, datetime
from uuid import uuid4

from app.chat.schemas import MessageRead
from app.core.enums import ChatMessageType, NotificationType


class TestMessageReadSchema:
    def test_user_message_schema(self) -> None:
        msg = MessageRead(
            id=uuid4(),
            side="requester",
            name="Иван Иванов",
            text="Hello",
            media=[],
            message_type=ChatMessageType.USER,
            notification_type=None,
            notification_body=None,
            created_at=datetime.now(tz=UTC),
            read_at=None,
        )
        assert msg.message_type == "user"
        assert msg.name == "Иван Иванов"

    def test_notification_message_schema(self) -> None:
        msg = MessageRead(
            id=uuid4(),
            side="requester",
            name=None,
            text=None,
            media=[],
            message_type=ChatMessageType.NOTIFICATION,
            notification_type=NotificationType.STATUS_CHANGED,
            notification_body={"old_status": "pending", "new_status": "offered"},
            created_at=datetime.now(tz=UTC),
            read_at=None,
        )
        assert msg.message_type == "notification"
        assert msg.notification_type == "status_changed"
        assert msg.notification_body == {"old_status": "pending", "new_status": "offered"}
        assert msg.name is None
