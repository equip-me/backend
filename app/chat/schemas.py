from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MediaAttachmentRead(BaseModel):
    id: str
    kind: str
    urls: dict[str, str]
    original_filename: str
    content_type: str


class MessageRead(BaseModel):
    id: UUID
    side: str
    name: str
    text: str | None
    media: list[MediaAttachmentRead]
    created_at: datetime
    read_at: datetime | None


class ChatStatusResponse(BaseModel):
    status: str
    unread_count: int
