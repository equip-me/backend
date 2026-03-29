from uuid import UUID

from pydantic import BaseModel

from app.core.enums import MediaContext, MediaKind, MediaStatus


class UploadUrlRequest(BaseModel):
    kind: MediaKind
    context: MediaContext
    filename: str
    content_type: str
    file_size: int


class UploadUrlResponse(BaseModel):
    media_id: UUID
    upload_url: str
    expires_in: int


class MediaStatusResponse(BaseModel):
    id: UUID
    status: MediaStatus
    kind: MediaKind
    context: MediaContext
    original_filename: str
    variants: dict[str, str]


class MediaPhotoRead(BaseModel):
    id: UUID
    large_url: str | None = None
    medium_url: str | None = None
    small_url: str | None = None
    position: int = 0


class MediaVideoRead(BaseModel):
    id: UUID
    full_url: str | None = None
    preview_url: str | None = None
    position: int = 0


class MediaDocumentRead(BaseModel):
    id: UUID
    url: str
    filename: str
    file_size: int
    position: int = 0


class ProfilePhotoRead(BaseModel):
    id: UUID
    medium_url: str
    small_url: str
