from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.enums import MediaKind, MediaOwnerType, MediaStatus
from app.core.exceptions import AppValidationError, NotFoundError, PermissionDeniedError
from app.media.models import Media
from app.media.schemas import (
    MediaDocumentRead,
    MediaPhotoRead,
    MediaVideoRead,
    ProfilePhotoRead,
    UploadUrlRequest,
    UploadUrlResponse,
)
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
        raise AppValidationError(
            f"Content type '{data.content_type}' is not allowed for {data.kind.value}",
            code="media.invalid_content_type",
            params={"content_type": data.content_type, "kind": data.kind.value},
        )

    max_size = _max_size_bytes(data.kind)
    if data.file_size > max_size:
        raise AppValidationError(
            f"File size exceeds maximum of {max_size // (1024 * 1024)} MB for {data.kind.value}",
            code="media.file_too_large",
            params={"max_mb": max_size // (1024 * 1024), "kind": data.kind.value},
        )

    media_id = uuid4()
    safe_filename = PurePosixPath(data.filename).name
    if not safe_filename:
        raise AppValidationError("Invalid filename", code="media.invalid_filename")
    upload_key = f"pending/{media_id}/{safe_filename}"

    await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=data.kind,
        context=data.context,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename=safe_filename,
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


@traced
async def confirm_upload(
    media: Media,
    storage: StorageClient,
) -> Media:
    if media.status != MediaStatus.PENDING_UPLOAD:
        raise AppValidationError(
            f"Media is in '{media.status}' state, expected 'pending_upload'",
            code="media.not_pending_upload",
            params={"status": media.status.value},
        )

    if not await storage.exists(media.upload_key):
        raise NotFoundError("Uploaded file not found in storage", code="media.upload_missing")

    media.status = MediaStatus.PROCESSING
    await media.save()

    from app.worker.settings import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job("process_media_job", str(media.id))

    return media


@traced
async def delete_media(media: Media, storage: StorageClient) -> None:
    await storage.delete_prefix(f"pending/{media.id}/")
    await storage.delete_prefix(f"media/{media.id}/")
    await media.delete()


@traced
async def delete_entity_media(
    owner_type: MediaOwnerType,
    owner_id: str,
    storage: StorageClient,
) -> None:
    """Delete all media for an entity (S3 files + DB records)."""
    media_list = await Media.filter(owner_type=owner_type, owner_id=owner_id).all()
    for media in media_list:
        await storage.delete_prefix(f"pending/{media.id}/")
        await storage.delete_prefix(f"media/{media.id}/")
        await media.delete()


@traced
async def cleanup_orphaned_media(storage: StorageClient, max_age_hours: int = 24) -> int:
    """Delete unattached media older than max_age_hours. Returns count of deleted records."""
    cutoff = datetime.now(tz=UTC) - timedelta(hours=max_age_hours)
    orphans = await Media.filter(
        owner_type=None,
        created_at__lt=cutoff,
        status__not=MediaStatus.FAILED,
    ).all()

    count = 0
    for media in orphans:
        await storage.delete_prefix(f"pending/{media.id}/")
        await storage.delete_prefix(f"media/{media.id}/")
        await media.delete()
        count += 1

    return count


@traced
async def retry_media(media: Media) -> Media:
    if media.status != MediaStatus.FAILED:
        raise AppValidationError("Only failed media can be retried", code="media.not_failed")
    media.status = MediaStatus.PROCESSING
    await media.save()

    from app.worker.settings import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job("process_media_job", str(media.id))

    return media


@traced
async def get_profile_photo(
    owner_type: MediaOwnerType,
    owner_id: str,
    storage: StorageClient,
) -> ProfilePhotoRead | None:
    """Get profile photo for an entity, generating presigned download URLs."""
    media = await Media.filter(
        owner_type=owner_type,
        owner_id=owner_id,
        kind=MediaKind.PHOTO,
        status=MediaStatus.READY,
    ).first()
    if media is None:
        return None

    settings = get_settings()
    expires = settings.storage.presigned_url_expiry_seconds

    medium_key = media.variants.get("medium", "")
    small_key = media.variants.get("small", "")

    return ProfilePhotoRead(
        id=media.id,
        medium_url=await storage.generate_download_url(medium_key, expires) if medium_key else "",
        small_url=await storage.generate_download_url(small_key, expires) if small_key else "",
    )


@traced
async def attach_profile_photo(
    media_id: UUID | None,
    owner_type: MediaOwnerType,
    owner_id: str,
    user: User,
    storage: StorageClient,
) -> None:
    """Attach a profile photo. Detaches existing photo (becomes orphan for cleanup)."""
    _ = storage  # reserved for future use

    # Detach any existing profile photo
    await Media.filter(
        owner_type=owner_type,
        owner_id=owner_id,
        kind=MediaKind.PHOTO,
    ).update(owner_type=None, owner_id=None)

    if media_id is None:
        return

    media = await Media.get_or_none(id=media_id).prefetch_related("uploaded_by")
    if media is None:
        raise NotFoundError("Media not found", code="media.not_found")
    if media.status != MediaStatus.READY:
        raise AppValidationError("Media is not ready", code="media.not_ready", params={"id": str(media_id)})

    uploader: User = media.uploaded_by
    if uploader.id != user.id:
        raise PermissionDeniedError("You can only attach your own uploads", code="media.not_uploader")
    if media.kind != MediaKind.PHOTO:
        raise AppValidationError(
            "Only photos can be used as profile photo",
            code="media.wrong_kind",
            params={"id": str(media_id), "kind": media.kind.value, "expected_kind": MediaKind.PHOTO.value},
        )

    media.owner_type = owner_type
    media.owner_id = owner_id
    await media.save()


@traced
async def attach_listing_media(
    listing_id: str,
    photo_ids: list[UUID],
    video_ids: list[UUID],
    document_ids: list[UUID],
    user: User,
    storage: StorageClient,
) -> None:
    """Attach media to a listing. Detaches all current media first (removed ones become orphans)."""
    _ = storage  # reserved for future use
    settings = get_settings()

    if len(photo_ids) > settings.media.listing_limits_max_photos:
        raise AppValidationError(
            f"Maximum {settings.media.listing_limits_max_photos} photos allowed",
            code="media.limit_exceeded",
            params={"max": settings.media.listing_limits_max_photos, "kind": MediaKind.PHOTO.value},
        )
    if len(video_ids) > settings.media.listing_limits_max_videos:
        raise AppValidationError(
            f"Maximum {settings.media.listing_limits_max_videos} videos allowed",
            code="media.limit_exceeded",
            params={"max": settings.media.listing_limits_max_videos, "kind": MediaKind.VIDEO.value},
        )
    if len(document_ids) > settings.media.listing_limits_max_documents:
        raise AppValidationError(
            f"Maximum {settings.media.listing_limits_max_documents} documents allowed",
            code="media.limit_exceeded",
            params={"max": settings.media.listing_limits_max_documents, "kind": MediaKind.DOCUMENT.value},
        )

    # Detach all current media from this listing
    await Media.filter(
        owner_type=MediaOwnerType.LISTING,
        owner_id=listing_id,
    ).update(owner_type=None, owner_id=None)

    # Attach new media with position ordering
    all_ids_with_kind: list[tuple[UUID, MediaKind]] = [
        *[(pid, MediaKind.PHOTO) for pid in photo_ids],
        *[(vid, MediaKind.VIDEO) for vid in video_ids],
        *[(did, MediaKind.DOCUMENT) for did in document_ids],
    ]
    for position, (media_id, expected_kind) in enumerate(all_ids_with_kind):
        media = await Media.get_or_none(id=media_id).prefetch_related("uploaded_by")
        if media is None:
            raise NotFoundError(f"Media {media_id} not found", code="media.not_found")
        uploader: User = media.uploaded_by
        if uploader.id != user.id:
            raise PermissionDeniedError(f"Media {media_id} was not uploaded by you", code="media.not_uploader")
        if media.status != MediaStatus.READY:
            raise AppValidationError(
                f"Media {media_id} is not ready",
                code="media.not_ready",
                params={"id": str(media_id)},
            )
        if media.kind != expected_kind:
            raise AppValidationError(
                f"Media {media_id} is {media.kind.value}, expected {expected_kind.value}",
                code="media.wrong_kind",
                params={"id": str(media_id), "kind": media.kind.value, "expected_kind": expected_kind.value},
            )

        media.owner_type = MediaOwnerType.LISTING
        media.owner_id = listing_id
        media.position = position
        await media.save()


@traced
async def get_listing_media(
    listing_id: str,
    storage: StorageClient,
) -> tuple[list[MediaPhotoRead], list[MediaVideoRead], list[MediaDocumentRead]]:
    """Get all media for a listing with presigned download URLs."""
    settings = get_settings()
    expires = settings.storage.presigned_url_expiry_seconds

    media_list = await Media.filter(
        owner_type=MediaOwnerType.LISTING,
        owner_id=listing_id,
        status=MediaStatus.READY,
    ).order_by("position", "-created_at")

    photos: list[MediaPhotoRead] = []
    videos: list[MediaVideoRead] = []
    documents: list[MediaDocumentRead] = []

    for m in media_list:
        if m.kind == MediaKind.PHOTO:
            photos.append(
                MediaPhotoRead(
                    id=m.id,
                    large_url=(
                        await storage.generate_download_url(m.variants["large"], expires)
                        if "large" in m.variants
                        else None
                    ),
                    medium_url=(
                        await storage.generate_download_url(m.variants["medium"], expires)
                        if "medium" in m.variants
                        else None
                    ),
                    small_url=(
                        await storage.generate_download_url(m.variants["small"], expires)
                        if "small" in m.variants
                        else None
                    ),
                    position=m.position,
                )
            )
        elif m.kind == MediaKind.VIDEO:
            videos.append(
                MediaVideoRead(
                    id=m.id,
                    full_url=(
                        await storage.generate_download_url(m.variants["full"], expires)
                        if "full" in m.variants
                        else None
                    ),
                    preview_url=(
                        await storage.generate_download_url(m.variants["preview"], expires)
                        if "preview" in m.variants
                        else None
                    ),
                    position=m.position,
                )
            )
        elif m.kind == MediaKind.DOCUMENT:
            original_key = m.variants.get("original", "")
            documents.append(
                MediaDocumentRead(
                    id=m.id,
                    url=await storage.generate_download_url(original_key, expires) if original_key else "",
                    filename=m.original_filename,
                    file_size=m.file_size,
                    position=m.position,
                )
            )

    return photos, videos, documents
