import io
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from arq.connections import RedisSettings
from PIL import Image

from app.core.enums import MediaContext, MediaKind, MediaOwnerType, MediaStatus
from app.media.models import Media
from app.media.worker import (
    WorkerSettings,
    _get_variant_specs,
    _process_document,
    _process_photo,
    _process_video,
    cleanup_orphans_cron,
    process_media_job,
)
from app.users.models import User


def _make_jpeg(width: int = 200, height: int = 150) -> bytes:
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def _create_user(user_id: str, email: str) -> User:
    return await User.create(
        id=user_id,
        email=email,
        hashed_password="x",
        phone="+79991234567",
        name="Test",
        surname="Worker",
    )


async def _create_media(
    user: User,
    kind: MediaKind = MediaKind.PHOTO,
    context: MediaContext = MediaContext.USER_PROFILE,
    status: MediaStatus = MediaStatus.PROCESSING,
    **kwargs: Any,
) -> Media:
    media_id = kwargs.pop("id", uuid4())
    return await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=kind,
        context=context,
        status=status,
        original_filename=kwargs.pop("original_filename", "test.jpg"),
        content_type=kwargs.pop("content_type", "image/jpeg"),
        file_size=kwargs.pop("file_size", 1024),
        upload_key=kwargs.pop("upload_key", f"pending/{media_id}/test.jpg"),
        **kwargs,
    )


# ── _get_variant_specs tests ────────────────────────────────


async def test_get_variant_specs_photo_user_profile() -> None:
    user = await _create_user("WRKR01", "worker01@example.com")
    media = await _create_media(user, kind=MediaKind.PHOTO, context=MediaContext.USER_PROFILE)

    specs = _get_variant_specs(media)

    names = [s["name"] for s in specs]
    assert "medium" in names
    assert "small" in names
    assert len(specs) == 2


async def test_get_variant_specs_photo_listing() -> None:
    user = await _create_user("WRKR02", "worker02@example.com")
    media = await _create_media(user, kind=MediaKind.PHOTO, context=MediaContext.LISTING)

    specs = _get_variant_specs(media)

    names = [s["name"] for s in specs]
    assert "large" in names
    assert "medium" in names
    assert "small" in names
    assert len(specs) == 3


async def test_get_variant_specs_video_listing() -> None:
    user = await _create_user("WRKR03", "worker03@example.com")
    media = await _create_media(user, kind=MediaKind.VIDEO, context=MediaContext.LISTING)

    specs = _get_variant_specs(media)

    names = [s["name"] for s in specs]
    assert "full" in names
    assert "preview" in names
    assert len(specs) == 2


async def test_get_variant_specs_document() -> None:
    user = await _create_user("WRKR04", "worker04@example.com")
    media = await _create_media(user, kind=MediaKind.DOCUMENT, context=MediaContext.LISTING)

    specs = _get_variant_specs(media)

    assert specs == []


# ── process_media_job tests ──────────────────────────────


async def test_process_media_job_photo() -> None:
    user = await _create_user("WRKR05", "worker05@example.com")
    media = await _create_media(
        user,
        kind=MediaKind.PHOTO,
        context=MediaContext.LISTING,
        original_filename="photo.jpg",
    )

    mock_storage = AsyncMock()
    mock_storage.download.return_value = _make_jpeg(400, 300)

    with patch("app.media.worker._get_storage", return_value=mock_storage):
        await process_media_job({}, str(media.id))

    refreshed = await Media.get(id=media.id)
    assert refreshed.status == MediaStatus.READY
    assert refreshed.processed_at is not None
    assert len(refreshed.variants) > 0

    mock_storage.download.assert_called_once_with(media.upload_key)
    assert mock_storage.upload.call_count == 3  # large, medium, small for listing
    mock_storage.delete.assert_called_once_with(media.upload_key)


async def test_process_media_job_document() -> None:
    user = await _create_user("WRKR06", "worker06@example.com")
    media = await _create_media(
        user,
        kind=MediaKind.DOCUMENT,
        context=MediaContext.LISTING,
        original_filename="spec.pdf",
        content_type="application/pdf",
    )

    mock_storage = AsyncMock()
    mock_storage.download.return_value = b"%PDF-1.4 fake pdf"

    with patch("app.media.worker._get_storage", return_value=mock_storage):
        await process_media_job({}, str(media.id))

    refreshed = await Media.get(id=media.id)
    assert refreshed.status == MediaStatus.READY
    assert "original" in refreshed.variants
    mock_storage.delete.assert_called_once_with(media.upload_key)


async def test_process_media_job_not_found() -> None:
    random_id = str(uuid4())
    # Should not raise any error
    await process_media_job({}, random_id)


async def test_process_media_job_failure() -> None:
    user = await _create_user("WRKR07", "worker07@example.com")
    media = await _create_media(user, kind=MediaKind.PHOTO, context=MediaContext.USER_PROFILE)

    mock_storage = AsyncMock()
    mock_storage.download.side_effect = RuntimeError("S3 connection failed")

    with patch("app.media.worker._get_storage", return_value=mock_storage):
        with pytest.raises(RuntimeError, match="S3 connection failed"):
            await process_media_job({}, str(media.id))

    refreshed = await Media.get(id=media.id)
    assert refreshed.status == MediaStatus.FAILED


# ── _process_photo orchestration ─────────────────────────


async def test_process_photo_orchestration() -> None:
    user = await _create_user("WRKR08", "worker08@example.com")
    media = await _create_media(user, kind=MediaKind.PHOTO, context=MediaContext.USER_PROFILE)

    mock_storage = AsyncMock()
    mock_storage.download.return_value = _make_jpeg(400, 300)

    await _process_photo(media, mock_storage)

    mock_storage.download.assert_called_once_with(media.upload_key)
    # profile variants: medium + small
    assert mock_storage.upload.call_count == 2
    for call in mock_storage.upload.call_args_list:
        args = call[0]
        assert args[0].startswith(f"media/{media.id}/")
        assert args[0].endswith(".webp")
        assert args[2] == "image/webp"
    mock_storage.delete.assert_called_once_with(media.upload_key)
    assert "medium" in media.variants
    assert "small" in media.variants


# ── _process_video orchestration ─────────────────────────


async def test_process_video_orchestration() -> None:
    user = await _create_user("WRKR09", "worker09@example.com")
    media = await _create_media(
        user,
        kind=MediaKind.VIDEO,
        context=MediaContext.LISTING,
        original_filename="clip.mp4",
        content_type="video/mp4",
    )

    mock_storage = AsyncMock()
    mock_storage.download.return_value = b"fake video data"

    mock_process_video = AsyncMock(return_value={"full": b"full webm", "preview": b"preview webm"})

    with patch("app.media.processing.process_video", mock_process_video):
        await _process_video(media, mock_storage)

    mock_storage.download.assert_called_once_with(media.upload_key)
    assert mock_storage.upload.call_count == 2
    mock_storage.delete.assert_called_once_with(media.upload_key)
    assert "full" in media.variants
    assert "preview" in media.variants


# ── _process_document orchestration ──────────────────────


async def test_process_document_orchestration() -> None:
    user = await _create_user("WRKR10", "worker10@example.com")
    media = await _create_media(
        user,
        kind=MediaKind.DOCUMENT,
        context=MediaContext.LISTING,
        original_filename="report.pdf",
        content_type="application/pdf",
    )

    mock_storage = AsyncMock()
    mock_storage.download.return_value = b"pdf bytes"

    await _process_document(media, mock_storage)

    mock_storage.download.assert_called_once_with(media.upload_key)
    mock_storage.upload.assert_called_once()
    upload_args = mock_storage.upload.call_args[0]
    assert upload_args[0] == f"media/{media.id}/report.pdf"
    assert upload_args[1] == b"pdf bytes"
    assert upload_args[2] == "application/pdf"
    mock_storage.delete.assert_called_once_with(media.upload_key)
    assert media.variants == {"original": f"media/{media.id}/report.pdf"}


# ── cleanup_orphans_cron ─────────────────────────────────


async def test_cleanup_orphans_cron() -> None:
    user = await _create_user("WRKR11", "worker11@example.com")

    # Create an old orphan
    orphan = await _create_media(
        user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.READY,
    )
    await Media.filter(id=orphan.id).update(
        created_at=datetime.now(tz=UTC) - timedelta(hours=48),
    )

    # Create an attached media (should not be deleted)
    attached = await _create_media(
        user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.READY,
    )
    await Media.filter(id=attached.id).update(
        owner_type=MediaOwnerType.USER,
        owner_id="WRKR11",
        created_at=datetime.now(tz=UTC) - timedelta(hours=48),
    )

    mock_storage = AsyncMock()

    with patch("app.media.worker._get_storage", return_value=mock_storage):
        await cleanup_orphans_cron({})

    assert await Media.get_or_none(id=orphan.id) is None
    assert await Media.get_or_none(id=attached.id) is not None


# ── WorkerSettings.redis_settings ────────────────────────


async def test_worker_settings_redis_settings() -> None:
    assert isinstance(WorkerSettings.redis_settings, RedisSettings)
