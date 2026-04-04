"""End-to-end media upload tests against real MinIO and ffmpeg."""

import asyncio
import io
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings
from app.core.enums import MediaContext, MediaKind, MediaStatus
from app.media.models import Media
from app.media.storage import StorageClient
from app.users.models import User
from app.worker.media import process_media_job

pytestmark = pytest.mark.e2e

_HAS_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.fixture
async def real_storage() -> StorageClient:
    settings = get_settings()
    client = StorageClient(
        endpoint_url=settings.storage.endpoint_url,
        presigned_endpoint_url=settings.storage.presigned_endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        bucket=settings.storage.bucket,
    )
    await client.ensure_bucket()
    return client


@pytest.fixture
async def db_user() -> User:
    return await User.create(
        id="TSTE2E",
        email="e2e-media@example.com",
        hashed_password="x",
        phone="+79990001122",
        name="E2E",
        surname="Tester",
    )


def _make_jpeg(width: int = 800, height: int = 600) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _make_minimal_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF\n"
    )


async def _generate_test_video(output_path: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=1:size=320x240:rate=15",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=1",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-shortest",
        str(output_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = f"ffmpeg failed to generate test video: {stderr.decode()}"
        raise RuntimeError(msg)


async def _upload_via_presigned_url(url: str, data: bytes, content_type: str) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.put(url, content=data, headers={"Content-Type": content_type})
        resp.raise_for_status()


async def test_photo_e2e(real_storage: StorageClient, db_user: User) -> None:
    media_id = uuid4()
    upload_key = f"pending/{media_id}/photo.jpg"

    media = await Media.create(
        id=media_id,
        uploaded_by=db_user,
        kind=MediaKind.PHOTO,
        context=MediaContext.LISTING,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="photo.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=upload_key,
    )

    jpeg_data = _make_jpeg(800, 600)
    presigned_url = await real_storage.generate_upload_url(upload_key, "image/jpeg", expires=300)
    await _upload_via_presigned_url(presigned_url, jpeg_data, "image/jpeg")

    assert await real_storage.exists(upload_key)

    media.status = MediaStatus.PROCESSING
    await media.save()

    try:
        with patch("app.worker.media._get_storage", return_value=real_storage):
            await process_media_job({}, str(media.id))

        await media.refresh_from_db()
        assert media.status == MediaStatus.READY
        assert "large" in media.variants
        assert "medium" in media.variants
        assert "small" in media.variants

        expected_max_widths = {"large": 1200, "medium": 600, "small": 200}
        for variant_name, max_width in expected_max_widths.items():
            variant_key = media.variants[variant_name]
            assert await real_storage.exists(variant_key)

            variant_data = await real_storage.download(variant_key)
            variant_img = Image.open(io.BytesIO(variant_data))
            assert variant_img.format == "WEBP"
            assert variant_img.width <= max_width

        assert not await real_storage.exists(upload_key)
    finally:
        await real_storage.delete_prefix(f"pending/{media_id}/")
        await real_storage.delete_prefix(f"media/{media_id}/")


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not available")
async def test_video_e2e(real_storage: StorageClient, db_user: User) -> None:
    media_id = uuid4()
    original_filename = "test_video.mp4"
    upload_key = f"pending/{media_id}/{original_filename}"

    media = await Media.create(
        id=media_id,
        uploaded_by=db_user,
        kind=MediaKind.VIDEO,
        context=MediaContext.LISTING,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename=original_filename,
        content_type="video/mp4",
        file_size=1024,
        upload_key=upload_key,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = Path(tmpdir) / original_filename
        await _generate_test_video(video_path)
        video_data = video_path.read_bytes()

    presigned_url = await real_storage.generate_upload_url(upload_key, "video/mp4", expires=300)
    await _upload_via_presigned_url(presigned_url, video_data, "video/mp4")

    assert await real_storage.exists(upload_key)

    media.status = MediaStatus.PROCESSING
    await media.save()

    try:
        with patch("app.worker.media._get_storage", return_value=real_storage):
            await process_media_job({}, str(media.id))

        await media.refresh_from_db()
        assert media.status == MediaStatus.READY
        assert "full" in media.variants
        assert "preview" in media.variants

        for variant_name in ("full", "preview"):
            variant_key = media.variants[variant_name]
            assert await real_storage.exists(variant_key)

        full_data = await real_storage.download(media.variants["full"])
        assert full_data[:4] == b"\x1a\x45\xdf\xa3", "Expected WebM (EBML) magic bytes"

        assert not await real_storage.exists(upload_key)
    finally:
        await real_storage.delete_prefix(f"pending/{media_id}/")
        await real_storage.delete_prefix(f"media/{media_id}/")


async def test_document_e2e(real_storage: StorageClient, db_user: User) -> None:
    media_id = uuid4()
    upload_key = f"pending/{media_id}/document.pdf"
    pdf_data = _make_minimal_pdf()

    media = await Media.create(
        id=media_id,
        uploaded_by=db_user,
        kind=MediaKind.DOCUMENT,
        context=MediaContext.LISTING,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="document.pdf",
        content_type="application/pdf",
        file_size=len(pdf_data),
        upload_key=upload_key,
    )

    presigned_url = await real_storage.generate_upload_url(upload_key, "application/pdf", expires=300)
    await _upload_via_presigned_url(presigned_url, pdf_data, "application/pdf")

    assert await real_storage.exists(upload_key)

    media.status = MediaStatus.PROCESSING
    await media.save()

    try:
        with patch("app.worker.media._get_storage", return_value=real_storage):
            await process_media_job({}, str(media.id))

        await media.refresh_from_db()
        assert media.status == MediaStatus.READY
        assert "original" in media.variants

        original_key = media.variants["original"]
        assert await real_storage.exists(original_key)

        downloaded = await real_storage.download(original_key)
        assert downloaded == pdf_data

        assert not await real_storage.exists(upload_key)
    finally:
        await real_storage.delete_prefix(f"pending/{media_id}/")
        await real_storage.delete_prefix(f"media/{media_id}/")


async def test_profile_photo_e2e(real_storage: StorageClient, db_user: User) -> None:
    media_id = uuid4()
    upload_key = f"pending/{media_id}/avatar.jpg"

    media = await Media.create(
        id=media_id,
        uploaded_by=db_user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="avatar.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=upload_key,
    )

    jpeg_data = _make_jpeg(800, 600)
    presigned_url = await real_storage.generate_upload_url(upload_key, "image/jpeg", expires=300)
    await _upload_via_presigned_url(presigned_url, jpeg_data, "image/jpeg")

    media.status = MediaStatus.PROCESSING
    await media.save()

    try:
        with patch("app.worker.media._get_storage", return_value=real_storage):
            await process_media_job({}, str(media.id))

        await media.refresh_from_db()
        assert media.status == MediaStatus.READY

        assert "medium" in media.variants
        assert "small" in media.variants
        assert "large" not in media.variants

        expected_max_widths = {"medium": 600, "small": 200}
        for variant_name, max_width in expected_max_widths.items():
            variant_key = media.variants[variant_name]
            assert await real_storage.exists(variant_key)

            variant_data = await real_storage.download(variant_key)
            variant_img = Image.open(io.BytesIO(variant_data))
            assert variant_img.format == "WEBP"
            assert variant_img.width <= max_width

        assert not await real_storage.exists(upload_key)
    finally:
        await real_storage.delete_prefix(f"pending/{media_id}/")
        await real_storage.delete_prefix(f"media/{media_id}/")


async def test_processing_failure_e2e(real_storage: StorageClient, db_user: User) -> None:
    media_id = uuid4()
    upload_key = f"pending/{media_id}/bad.jpg"

    media = await Media.create(
        id=media_id,
        uploaded_by=db_user,
        kind=MediaKind.PHOTO,
        context=MediaContext.LISTING,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="bad.jpg",
        content_type="image/jpeg",
        file_size=100,
        upload_key=upload_key,
    )

    bad_data = b"not an image at all"
    presigned_url = await real_storage.generate_upload_url(upload_key, "image/jpeg", expires=300)
    await _upload_via_presigned_url(presigned_url, bad_data, "image/jpeg")

    media.status = MediaStatus.PROCESSING
    await media.save()

    try:
        with patch("app.worker.media._get_storage", return_value=real_storage):
            with pytest.raises(UnidentifiedImageError):
                await process_media_job({}, str(media.id))

        await media.refresh_from_db()
        assert media.status == MediaStatus.FAILED

        assert await real_storage.exists(upload_key)
    finally:
        await real_storage.delete_prefix(f"pending/{media_id}/")
        await real_storage.delete_prefix(f"media/{media_id}/")
