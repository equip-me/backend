from app.core.enums import ChatMessageType, ChatSide, NotificationType


class TestChatNotificationEnums:
    def test_chat_message_type_values(self) -> None:
        assert ChatMessageType.USER.value == "user"
        assert ChatMessageType.NOTIFICATION.value == "notification"

    def test_notification_type_values(self) -> None:
        assert NotificationType.STATUS_CHANGED.value == "status_changed"

    def test_chat_side_values(self) -> None:
        assert ChatSide.REQUESTER.value == "requester"
        assert ChatSide.ORGANIZATION.value == "organization"
