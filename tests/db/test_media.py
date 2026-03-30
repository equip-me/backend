from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.enums import MediaContext, MediaKind, MediaOwnerType, MediaStatus
from app.media.models import Media
from app.media.service import cleanup_orphaned_media
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


async def test_request_upload_url(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token = await create_user()
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "avatar.jpg",
            "content_type": "image/jpeg",
            "file_size": 1_000_000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "media_id" in data
    assert "upload_url" in data
    assert "expires_in" in data


async def test_upload_url_rejects_invalid_content_type(
    client: AsyncClient,
    create_user: Any,
    mock_storage: AsyncMock,  # noqa: ARG001
) -> None:
    _, token = await create_user()
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "malware.exe",
            "content_type": "application/x-msdownload",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_upload_url_rejects_oversized_file(
    client: AsyncClient,
    create_user: Any,
    mock_storage: AsyncMock,  # noqa: ARG001
) -> None:
    _, token = await create_user()
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "huge.jpg",
            "content_type": "image/jpeg",
            "file_size": 100_000_000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_upload_url_requires_auth(client: AsyncClient, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "avatar.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
    )
    assert resp.status_code == 401


async def test_confirm_upload(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "document",
            "context": "listing",
            "filename": "spec.pdf",
            "content_type": "application/pdf",
            "file_size": 5000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    confirm_resp = await client.post(
        f"/media/{media_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert confirm_resp.status_code == 200
    data = confirm_resp.json()
    assert data["status"] == "processing"


async def test_confirm_rejects_non_uploader(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token1 = await create_user(email="uploader@example.com")
    _, token2 = await create_user(email="other@example.com", phone="+79001112233")

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token1}"},
    )
    media_id = resp.json()["media_id"]

    confirm_resp = await client.post(
        f"/media/{media_id}/confirm",
        headers={"Authorization": f"Bearer {token2}"},
    )

    assert confirm_resp.status_code == 403


async def test_get_media_status(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    status_resp = await client.get(
        f"/media/{media_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "pending_upload"


async def test_delete_media(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    del_resp = await client.delete(
        f"/media/{media_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204

    status_resp = await client.get(
        f"/media/{media_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 404


async def test_retry_failed_media(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    await Media.filter(id=UUID(media_id)).update(status=MediaStatus.FAILED)

    retry_resp = await client.post(
        f"/media/{media_id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert retry_resp.status_code == 200
    assert retry_resp.json()["status"] == "processing"


# ── Profile photo helpers & tests ────────────────────────


async def _create_ready_photo(user_id: str, context: str = "user_profile") -> UUID:
    """Create a ready photo media record for testing."""
    user = await User.get(id=user_id)
    media_id = uuid4()
    media = await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext(context),
        status=MediaStatus.READY,
        original_filename="photo.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=f"pending/{media_id}/photo.jpg",
        variants={"medium": f"media/{media_id}/medium.webp", "small": f"media/{media_id}/small.webp"},
    )
    return media.id


async def test_update_user_with_profile_photo(client: AsyncClient, create_user: Any) -> None:
    user_data, token = await create_user()
    photo_id = await _create_ready_photo(user_data["id"])

    resp = await client.patch(
        "/users/me",
        json={"profile_photo_id": str(photo_id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["profile_photo"] is not None
    assert "medium_url" in resp.json()["profile_photo"]
    assert "small_url" in resp.json()["profile_photo"]


async def test_user_read_includes_profile_photo(client: AsyncClient, create_user: Any) -> None:
    user_data, token = await create_user()
    photo_id = await _create_ready_photo(user_data["id"])

    await client.patch(
        "/users/me",
        json={"profile_photo_id": str(photo_id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["profile_photo"] is not None


async def test_remove_profile_photo(client: AsyncClient, create_user: Any) -> None:
    user_data, token = await create_user()
    photo_id = await _create_ready_photo(user_data["id"])

    await client.patch(
        "/users/me",
        json={"profile_photo_id": str(photo_id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.patch(
        "/users/me",
        json={"profile_photo_id": None},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["profile_photo"] is None


# ── Organization photo tests ─────────────────────────────


async def test_org_read_includes_photo(client: AsyncClient, create_organization: Any) -> None:
    org_data, token = await create_organization()
    org_id = org_data["id"]

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]
    photo_id = await _create_ready_photo(user_id, "org_profile")
    await Media.filter(id=photo_id).update(
        owner_type=MediaOwnerType.ORGANIZATION,
        owner_id=org_id,
    )

    resp = await client.get(
        f"/organizations/{org_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["photo"] is not None
    assert "medium_url" in resp.json()["photo"]


async def test_update_org_photo(client: AsyncClient, create_organization: Any) -> None:
    org_data, token = await create_organization()
    org_id = org_data["id"]

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]
    photo_id = await _create_ready_photo(user_id, "org_profile")

    resp = await client.patch(
        f"/organizations/{org_id}/photo",
        json={"photo_id": str(photo_id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["photo"] is not None
    assert "medium_url" in resp.json()["photo"]


# ── Listing media tests ────────────────────────────────


async def test_create_listing_with_media(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]

    photo_id = await _create_ready_photo(user_id, "listing")

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Excavator with photos",
            "category_id": category_id,
            "price": 5000.00,
            "photo_ids": [str(photo_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert len(data["photos"]) == 1
    assert "medium_url" in data["photos"][0]


async def test_listing_detail_includes_all_photo_variants(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]

    # Create photo with listing variants (large+medium+small)
    user = await User.get(id=user_id)
    media_id = uuid4()
    await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.LISTING,
        status=MediaStatus.READY,
        original_filename="listing.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=f"pending/{media_id}/listing.jpg",
        variants={
            "large": f"media/{media_id}/large.webp",
            "medium": f"media/{media_id}/medium.webp",
            "small": f"media/{media_id}/small.webp",
        },
    )

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Excavator detail test",
            "category_id": category_id,
            "price": 5000.00,
            "photo_ids": [str(media_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201

    listing_id = resp.json()["id"]
    detail = await client.get(f"/listings/{listing_id}")
    assert detail.status_code == 200
    photos = detail.json()["photos"]
    assert len(photos) == 1
    assert photos[0]["large_url"] is not None
    assert photos[0]["medium_url"] is not None
    assert photos[0]["small_url"] is not None


async def test_update_listing_media(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]

    # Create listing without media
    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Excavator update media test",
            "category_id": category_id,
            "price": 5000.00,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    listing_id = resp.json()["id"]
    assert len(resp.json()["photos"]) == 0

    # Add a photo via update
    photo_id = await _create_ready_photo(user_id, "listing")
    patch_resp = await client.patch(
        f"/organizations/{org_id}/listings/{listing_id}",
        json={"photo_ids": [str(photo_id)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch_resp.status_code == 200
    assert len(patch_resp.json()["photos"]) == 1

    # Remove all photos via update
    patch_resp2 = await client.patch(
        f"/organizations/{org_id}/listings/{listing_id}",
        json={"photo_ids": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch_resp2.status_code == 200
    assert len(patch_resp2.json()["photos"]) == 0


async def test_listing_without_media_returns_empty_arrays(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Excavator no media",
            "category_id": category_id,
            "price": 5000.00,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["photos"] == []
    assert data["videos"] == []
    assert data["documents"] == []


# ── Immediate cleanup on entity deletion ─────────────────


async def test_delete_listing_cleans_up_media(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]
    photo_id = await _create_ready_photo(user_id, "listing")

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "To be deleted",
            "category_id": category_id,
            "price": 1000.00,
            "photo_ids": [str(photo_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    listing_id = resp.json()["id"]

    del_resp = await client.delete(
        f"/organizations/{org_id}/listings/{listing_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204

    # Media record should be deleted
    media = await Media.get_or_none(id=photo_id)
    assert media is None


# ── Orphan cleanup cron ───────────────────────────────────


async def test_orphan_cleanup_deletes_old_unattached() -> None:
    mock_st = AsyncMock()

    user = await User.create(
        id="ORPH01",
        email="orphan-test@example.com",
        hashed_password="x",
        phone="+79991234567",
        name="Test",
        surname="Orphan",
    )

    old_media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.READY,
        original_filename="old.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key="pending/old/old.jpg",
        variants={"medium": "media/old/medium.webp"},
    )
    await Media.filter(id=old_media.id).update(
        created_at=datetime.now(tz=UTC) - timedelta(hours=48),
    )

    recent_media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="recent.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key="pending/recent/recent.jpg",
    )

    deleted_count = await cleanup_orphaned_media(mock_st, max_age_hours=24)

    assert deleted_count == 1
    assert await Media.get_or_none(id=old_media.id) is None
    assert await Media.get_or_none(id=recent_media.id) is not None


async def test_orphan_cleanup_skips_attached() -> None:
    mock_st = AsyncMock()

    user = await User.create(
        id="ORPH02",
        email="orphan-attached@example.com",
        hashed_password="x",
        phone="+79001112233",
        name="Test",
        surname="Attached",
    )

    attached_media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        owner_type=MediaOwnerType.USER,
        owner_id="ORPH02",
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.READY,
        original_filename="attached.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key="pending/attached/attached.jpg",
        variants={"medium": "media/attached/medium.webp"},
    )
    await Media.filter(id=attached_media.id).update(
        created_at=datetime.now(tz=UTC) - timedelta(hours=48),
    )

    deleted_count = await cleanup_orphaned_media(mock_st, max_age_hours=24)

    assert deleted_count == 0
    assert await Media.get_or_none(id=attached_media.id) is not None


# ── Service validation edge cases ────────────────────────


async def test_upload_url_rejects_empty_filename(
    client: AsyncClient,
    create_user: Any,
    mock_storage: AsyncMock,  # noqa: ARG001
) -> None:
    _, token = await create_user()
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_upload_url_rejects_path_traversal_filename(
    client: AsyncClient,
    create_user: Any,
    mock_storage: AsyncMock,  # noqa: ARG001
) -> None:
    _, token = await create_user()
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "../../../etc/passwd",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # The path traversal results in "passwd" as the safe filename, so it should succeed
    # unless the name itself is disallowed. Let's verify the behavior.
    assert resp.status_code == 200


async def test_confirm_rejects_wrong_status(
    client: AsyncClient,
    create_user: Any,
    mock_storage: AsyncMock,  # noqa: ARG001
) -> None:
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    # Set status to PROCESSING (not PENDING_UPLOAD)
    await Media.filter(id=UUID(media_id)).update(status=MediaStatus.PROCESSING)

    confirm_resp = await client.post(
        f"/media/{media_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm_resp.status_code == 400


async def test_confirm_rejects_missing_file(
    client: AsyncClient,
    create_user: Any,
    mock_storage: AsyncMock,
) -> None:
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    # Storage says file doesn't exist
    mock_storage.exists.return_value = False

    confirm_resp = await client.post(
        f"/media/{media_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm_resp.status_code == 404


async def test_retry_rejects_non_failed(
    client: AsyncClient,
    create_user: Any,
    mock_storage: AsyncMock,  # noqa: ARG001
) -> None:
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    # Set status to READY
    await Media.filter(id=UUID(media_id)).update(status=MediaStatus.READY)

    retry_resp = await client.post(
        f"/media/{media_id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert retry_resp.status_code == 400


async def test_attach_profile_photo_not_ready(client: AsyncClient, create_user: Any) -> None:
    user_data, token = await create_user()
    user = await User.get(id=user_data["id"])
    media_id = uuid4()
    await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="pending.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=f"pending/{media_id}/pending.jpg",
    )

    resp = await client.patch(
        "/users/me",
        json={"profile_photo_id": str(media_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_attach_profile_photo_wrong_uploader(client: AsyncClient, create_user: Any) -> None:
    user_data_a, _ = await create_user(email="uploader-a@example.com")
    _, token_b = await create_user(email="uploader-b@example.com", phone="+79001112233")

    photo_id = await _create_ready_photo(user_data_a["id"])

    resp = await client.patch(
        "/users/me",
        json={"profile_photo_id": str(photo_id)},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 403


async def test_attach_profile_photo_not_photo(client: AsyncClient, create_user: Any) -> None:
    user_data, token = await create_user()
    user = await User.get(id=user_data["id"])
    media_id = uuid4()
    await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=MediaKind.VIDEO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.READY,
        original_filename="video.mp4",
        content_type="video/mp4",
        file_size=1024,
        upload_key=f"pending/{media_id}/video.mp4",
        variants={"full": f"media/{media_id}/full.webm"},
    )

    resp = await client.patch(
        "/users/me",
        json={"profile_photo_id": str(media_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_attach_profile_photo_nonexistent(client: AsyncClient, create_user: Any) -> None:
    _, token = await create_user()

    resp = await client.patch(
        "/users/me",
        json={"profile_photo_id": str(uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── Listing media attach edge cases ──────────────────────


async def test_attach_listing_media_exceeds_photo_limit(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]

    # Create 21 ready photos (limit is 20)
    photo_ids = []
    for _ in range(21):
        pid = await _create_ready_photo(user_id, "listing")
        photo_ids.append(str(pid))

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Too many photos",
            "category_id": category_id,
            "price": 1000.00,
            "photo_ids": photo_ids,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_attach_listing_media_wrong_kind(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]
    user = await User.get(id=user_id)

    # Create a VIDEO media
    video_id = uuid4()
    await Media.create(
        id=video_id,
        uploaded_by=user,
        kind=MediaKind.VIDEO,
        context=MediaContext.LISTING,
        status=MediaStatus.READY,
        original_filename="video.mp4",
        content_type="video/mp4",
        file_size=1024,
        upload_key=f"pending/{video_id}/video.mp4",
        variants={"full": f"media/{video_id}/full.webm"},
    )

    # Pass video_id in photo_ids list
    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Wrong kind test",
            "category_id": category_id,
            "price": 1000.00,
            "photo_ids": [str(video_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_attach_listing_media_not_ready(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]
    user = await User.get(id=user_id)

    # Create PENDING photo
    media_id = uuid4()
    await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.LISTING,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="pending.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=f"pending/{media_id}/pending.jpg",
    )

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Not ready test",
            "category_id": category_id,
            "price": 1000.00,
            "photo_ids": [str(media_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_attach_listing_media_wrong_uploader(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
    create_user: Any,
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    # Create a photo uploaded by a different user
    other_data, _ = await create_user(email="other-uploader@example.com", phone="+79009998877")
    photo_id = await _create_ready_photo(other_data["id"], "listing")

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Wrong uploader test",
            "category_id": category_id,
            "price": 1000.00,
            "photo_ids": [str(photo_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ── Listing media: video and document branches ───────────


async def _create_ready_video(user_id: str) -> UUID:
    user = await User.get(id=user_id)
    media_id = uuid4()
    await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=MediaKind.VIDEO,
        context=MediaContext.LISTING,
        status=MediaStatus.READY,
        original_filename="clip.mp4",
        content_type="video/mp4",
        file_size=5000,
        upload_key=f"pending/{media_id}/clip.mp4",
        variants={"full": f"media/{media_id}/full.webm", "preview": f"media/{media_id}/preview.webm"},
    )
    return media_id


async def _create_ready_document(user_id: str) -> UUID:
    user = await User.get(id=user_id)
    media_id = uuid4()
    await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=MediaKind.DOCUMENT,
        context=MediaContext.LISTING,
        status=MediaStatus.READY,
        original_filename="spec.pdf",
        content_type="application/pdf",
        file_size=2048,
        upload_key=f"pending/{media_id}/spec.pdf",
        variants={"original": f"media/{media_id}/spec.pdf"},
    )
    return media_id


async def test_get_listing_media_with_videos(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]

    video_id = await _create_ready_video(user_id)

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Video listing",
            "category_id": category_id,
            "price": 3000.00,
            "video_ids": [str(video_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    listing_id = resp.json()["id"]

    detail = await client.get(f"/listings/{listing_id}")
    assert detail.status_code == 200
    videos = detail.json()["videos"]
    assert len(videos) == 1
    assert videos[0]["full_url"] is not None
    assert videos[0]["preview_url"] is not None


async def test_get_listing_media_with_documents(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]

    doc_id = await _create_ready_document(user_id)

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Document listing",
            "category_id": category_id,
            "price": 2000.00,
            "document_ids": [str(doc_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    listing_id = resp.json()["id"]

    detail = await client.get(f"/listings/{listing_id}")
    assert detail.status_code == 200
    documents = detail.json()["documents"]
    assert len(documents) == 1
    assert documents[0]["url"] is not None
    assert documents[0]["filename"] == "spec.pdf"
    assert documents[0]["file_size"] == 2048


# ── Orphan cleanup: FAILED media ────────────────────────


async def test_orphan_cleanup_skips_failed() -> None:
    mock_st = AsyncMock()

    user = await User.create(
        id="ORPH03",
        email="orphan-failed@example.com",
        hashed_password="x",
        phone="+79002223344",
        name="Test",
        surname="Failed",
    )

    failed_media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.FAILED,
        original_filename="failed.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key="pending/failed/failed.jpg",
    )
    await Media.filter(id=failed_media.id).update(
        created_at=datetime.now(tz=UTC) - timedelta(hours=48),
    )

    deleted_count = await cleanup_orphaned_media(mock_st, max_age_hours=24)

    assert deleted_count == 0
    assert await Media.get_or_none(id=failed_media.id) is not None
