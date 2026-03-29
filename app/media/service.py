from uuid import uuid4

from app.core.config import get_settings
from app.core.enums import MediaKind, MediaStatus
from app.core.exceptions import AppValidationError
from app.media.models import Media
from app.media.schemas import UploadUrlRequest, UploadUrlResponse
from app.media.storage import StorageClient
from app.observability.tracing import traced
from app.users.models import User


def _max_size_bytes(kind: MediaKind) -> int:
    settings = get_settings()
    mb = {
        MediaKind.PHOTO: settings.media.max_photo_size_mb,
        MediaKind.VIDEO: settings.media.max_video_size_mb,
        MediaKind.DOCUMENT: settings.media.max_document_size_mb,
    }[kind]
    return mb * 1024 * 1024


def _allowed_types(kind: MediaKind) -> list[str]:
    settings = get_settings()
    return {
        MediaKind.PHOTO: settings.media.allowed_photo_types,
        MediaKind.VIDEO: settings.media.allowed_video_types,
        MediaKind.DOCUMENT: settings.media.allowed_document_types,
    }[kind]


@traced
async def request_upload_url(
    data: UploadUrlRequest,
    user: User,
    storage: StorageClient,
) -> UploadUrlResponse:
    if data.content_type not in _allowed_types(data.kind):
        raise AppValidationError(f"Content type '{data.content_type}' is not allowed for {data.kind.value}")

    max_size = _max_size_bytes(data.kind)
    if data.file_size > max_size:
        raise AppValidationError(f"File size exceeds maximum of {max_size // (1024 * 1024)} MB for {data.kind.value}")

    media_id = uuid4()
    upload_key = f"pending/{media_id}/{data.filename}"

    await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=data.kind,
        context=data.context,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename=data.filename,
        content_type=data.content_type,
        file_size=data.file_size,
        upload_key=upload_key,
    )

    settings = get_settings()
    expires = settings.storage.presigned_url_expiry_seconds
    upload_url = await storage.generate_upload_url(upload_key, data.content_type, expires)

    return UploadUrlResponse(
        media_id=media_id,
        upload_url=upload_url,
        expires_in=expires,
    )
