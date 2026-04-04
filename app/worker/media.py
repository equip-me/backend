import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.enums import MediaKind, MediaStatus
from app.media.models import Media
from app.media.processing import process_photo
from app.media.storage import StorageClient

logger = logging.getLogger(__name__)

_CONTEXT_TO_VARIANT_SET: dict[str, str] = {
    "user_profile": "profile",
    "org_profile": "profile",
    "listing": "listing",
    "chat": "chat",
}


def _get_storage() -> StorageClient:
    settings = get_settings()
    return StorageClient(
        endpoint_url=settings.storage.endpoint_url,
        presigned_endpoint_url=settings.storage.presigned_endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        bucket=settings.storage.bucket,
    )


def _get_variant_specs(media: Media) -> list[dict[str, Any]]:
    settings = get_settings()
    variant_key = _CONTEXT_TO_VARIANT_SET.get(media.context.value, media.context.value)
    if media.kind == MediaKind.PHOTO:
        return list(settings.media.photo_variant_sets.get(variant_key, []))
    if media.kind == MediaKind.VIDEO:
        return list(settings.media.video_variant_sets.get(variant_key, []))
    return []


async def process_media_job(_ctx: dict[str, Any], media_id: str) -> None:
    from tortoise import Tortoise

    from app.core.database import get_tortoise_config

    if not Tortoise._inited:
        await Tortoise.init(config=get_tortoise_config())

    media = await Media.get_or_none(id=UUID(media_id))
    if media is None:
        logger.error("Media %s not found", media_id)
        return

    storage = _get_storage()

    try:
        if media.kind == MediaKind.PHOTO:
            await _process_photo(media, storage)
        elif media.kind == MediaKind.VIDEO:
            await _process_video(media, storage)
        elif media.kind == MediaKind.DOCUMENT:
            await _process_document(media, storage)

        media.status = MediaStatus.READY
        media.processed_at = datetime.now(tz=UTC)
        await media.save()
        logger.info("Processed media %s (%s)", media_id, media.kind.value)

    except Exception:
        logger.exception("Failed to process media %s", media_id)
        media.status = MediaStatus.FAILED
        await media.save()
        raise


async def _process_photo(media: Media, storage: StorageClient) -> None:
    original_data = await storage.download(media.upload_key)
    variant_specs = _get_variant_specs(media)
    results = process_photo(original_data, variant_specs)

    variants: dict[str, str] = {}
    for name, data in results.items():
        key = f"media/{media.id}/{name}.webp"
        await storage.upload(key, data, "image/webp")
        variants[name] = key

    media.variants = variants
    await storage.delete(media.upload_key)


async def _process_video(media: Media, storage: StorageClient) -> None:
    from app.media.processing import process_video

    original_data = await storage.download(media.upload_key)
    variant_specs = _get_variant_specs(media)
    results = await process_video(original_data, variant_specs, media.original_filename)

    variants: dict[str, str] = {}
    for name, data in results.items():
        key = f"media/{media.id}/{name}.webm"
        await storage.upload(key, data, "video/webm")
        variants[name] = key

    media.variants = variants
    await storage.delete(media.upload_key)


async def _process_document(media: Media, storage: StorageClient) -> None:
    from app.media.processing import process_document

    original_data = await storage.download(media.upload_key)
    processed = process_document(original_data)

    key = f"media/{media.id}/{media.original_filename}"
    await storage.upload(key, processed, media.content_type)

    media.variants = {"original": key}
    await storage.delete(media.upload_key)


async def cleanup_orphans_cron(_ctx: dict[Any, Any]) -> None:
    from tortoise import Tortoise

    from app.core.database import get_tortoise_config
    from app.media.service import cleanup_orphaned_media

    if not Tortoise._inited:
        await Tortoise.init(config=get_tortoise_config())

    settings = get_settings()
    storage = _get_storage()
    deleted = await cleanup_orphaned_media(storage, settings.media.orphan_cleanup_after_hours)
    logger.info("Orphan cleanup: deleted %d media records", deleted)
