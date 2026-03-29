from typing import Any
from uuid import uuid4

import pytest

from app.core.enums import MediaContext, MediaKind, MediaStatus
from app.media.models import Media
from app.media.storage import StorageClient
from app.users.models import User


async def test_create_media_record(create_user: Any) -> None:
    user_data, _ = await create_user()
    user = await User.get(id=user_data["id"])

    media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="photo.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=f"pending/{uuid4()}/photo.jpg",
    )

    fetched = await Media.get(id=media.id)
    assert fetched.kind == MediaKind.PHOTO
    assert fetched.context == MediaContext.USER_PROFILE
    assert fetched.status == MediaStatus.PENDING_UPLOAD
    assert fetched.owner_type is None
    assert fetched.owner_id is None
    assert fetched.variants == {}


async def test_media_owner_assignment() -> None:
    from app.core.enums import MediaOwnerType

    user = await User.create(
        id="TSTU01",
        email="media-test@example.com",
        hashed_password="x",
        phone="+79991234567",
        name="Test",
        surname="User",
    )
    media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.LISTING,
        original_filename="listing.jpg",
        content_type="image/jpeg",
        file_size=2048,
        upload_key="pending/test/listing.jpg",
    )

    media.owner_type = MediaOwnerType.LISTING
    media.owner_id = "LST001"
    media.status = MediaStatus.READY
    media.variants = {"large": "media/test/large.webp", "medium": "media/test/medium.webp"}
    await media.save()

    fetched = await Media.get(id=media.id)
    assert fetched.owner_type == MediaOwnerType.LISTING
    assert fetched.owner_id == "LST001"
    assert fetched.status == MediaStatus.READY
    assert fetched.variants["large"] == "media/test/large.webp"


@pytest.fixture
async def storage() -> StorageClient:
    from app.core.config import get_settings

    settings = get_settings()
    client = StorageClient(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        bucket=settings.storage.bucket,
    )
    await client.ensure_bucket()
    return client


async def test_storage_upload_and_download(storage: StorageClient) -> None:
    key = "test/hello.txt"
    await storage.upload(key, b"hello world", "text/plain")

    assert await storage.exists(key)

    data = await storage.download(key)
    assert data == b"hello world"

    await storage.delete(key)
    assert not await storage.exists(key)


async def test_storage_presigned_upload_url(storage: StorageClient) -> None:
    url = await storage.generate_upload_url("test/upload.txt", "text/plain", expires=60)
    assert "test/upload.txt" in url
    assert "X-Amz-Signature" in url


async def test_storage_presigned_download_url(storage: StorageClient) -> None:
    key = "test/download.txt"
    await storage.upload(key, b"download me", "text/plain")

    url = await storage.generate_download_url(key, expires=60)
    assert "test/download.txt" in url
    assert "X-Amz-Signature" in url

    await storage.delete(key)


async def test_storage_delete_prefix(storage: StorageClient) -> None:
    await storage.upload("test/prefix/a.txt", b"a", "text/plain")
    await storage.upload("test/prefix/b.txt", b"b", "text/plain")
    await storage.upload("test/other/c.txt", b"c", "text/plain")

    await storage.delete_prefix("test/prefix/")

    assert not await storage.exists("test/prefix/a.txt")
    assert not await storage.exists("test/prefix/b.txt")
    assert await storage.exists("test/other/c.txt")

    await storage.delete("test/other/c.txt")
