from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.core.enums import ChatMessageType, NotificationType


class MediaAttachmentRead(BaseModel):
    id: str
    kind: str
    urls: dict[str, str]
    original_filename: str
    content_type: str


class MessageRead(BaseModel):
    id: UUID
    side: str
    name: str | None
    text: str | None
    media: list[MediaAttachmentRead]
    message_type: ChatMessageType
    notification_type: NotificationType | None
    notification_body: dict[str, str] | None
    created_at: datetime
    read_at: datetime | None


class ChatStatusResponse(BaseModel):
    status: str
    unread_count: int
