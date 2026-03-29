import logging
from datetime import UTC, datetime
from typing import Any, ClassVar, cast
from uuid import UUID

from arq import create_pool, run_worker
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings
from app.core.enums import MediaKind, MediaStatus
from app.media.models import Media
from app.media.processing import process_photo
from app.media.storage import StorageClient

logger = logging.getLogger(__name__)


def _get_storage() -> StorageClient:
    settings = get_settings()
    return StorageClient(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        bucket=settings.storage.bucket,
    )


def _get_variant_specs(media: Media) -> list[dict[str, Any]]:
    settings = get_settings()
    context = media.context.value
    if media.kind == MediaKind.PHOTO:
        return list(settings.media.photo_variant_sets.get(context, []))
    if media.kind == MediaKind.VIDEO:
        return list(settings.media.video_variant_sets.get(context, []))
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
    # Implemented in Task 9
    pass


async def get_arq_pool() -> ArqRedis:
    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.worker.redis_url)
    return await create_pool(redis_settings)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [process_media_job]
    max_jobs = 10

    @staticmethod
    def redis_settings() -> RedisSettings:
        settings = get_settings()
        return RedisSettings.from_dsn(settings.worker.redis_url)


if __name__ == "__main__":
    from arq.typing import WorkerSettingsBase

    run_worker(cast("type[WorkerSettingsBase]", WorkerSettings))
