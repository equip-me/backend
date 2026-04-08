from typing import Any, ClassVar
from uuid import uuid4

from tortoise import fields
from tortoise.models import Model

from app.core.enums import ChatMessageType, ChatSide, NotificationType


class ChatMessage(Model):
    id = fields.UUIDField(primary_key=True, default=uuid4)
    order: Any = fields.ForeignKeyField("models.Order", related_name="messages")
    order_id: str
    sender: Any = fields.ForeignKeyField("models.User", related_name="sent_messages", null=True)
    sender_id: str | None
    text = fields.TextField(null=True)
    media: Any = fields.JSONField(default=list)
    message_type = fields.CharEnumField(ChatMessageType, default=ChatMessageType.USER, max_length=20)
    notification_type = fields.CharEnumField(NotificationType, null=True, max_length=20)
    recipient_side = fields.CharEnumField(ChatSide, null=True, max_length=20)
    notification_body: Any = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    read_at = fields.DatetimeField(null=True)

    class Meta:
        table = "chat_messages"
        ordering: ClassVar[list[str]] = ["-created_at"]
