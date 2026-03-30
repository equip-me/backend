"""E2E tests for user registration, authentication, and profile management."""

import io
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from app.core.config import get_settings
from app.core.enums import MediaContext, MediaKind, MediaStatus, UserRole
from app.media.models import Media
from app.media.storage import StorageClient
from app.media.worker import process_media_job
from app.users.models import User

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_USER_DATA: dict[str, Any] = {
    "email": "alice@example.com",
    "password": "StrongPass1",
    "phone": "+79991234567",
    "name": "Alice",
    "surname": "Wonderland",
}


def _user_data(**overrides: Any) -> dict[str, Any]:
    return {**_USER_DATA, **overrides}


def _make_jpeg(width: int = 800, height: int = 600) -> bytes:
    img = Image.new("RGB", (width, height), color=(0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: httpx.AsyncClient, **overrides: Any) -> tuple[dict[str, Any], str]:
    """Register a user and return (user_read, token)."""
    data = _user_data(**overrides)
    resp = await client.post("/users/", json=data)
    assert resp.status_code == 200, resp.text
    token: str = resp.json()["access_token"]
    me = await client.get("/users/me", headers=_auth_header(token))
    assert me.status_code == 200, me.text
    return me.json(), token


@pytest.fixture
async def real_storage() -> StorageClient:
    settings = get_settings()
    storage = StorageClient(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        bucket=settings.storage.bucket,
    )
    await storage.ensure_bucket()
    return storage


async def _upload_via_presigned_url(url: str, data: bytes, content_type: str) -> None:
    async with httpx.AsyncClient() as c:
        resp = await c.put(url, content=data, headers={"Content-Type": content_type})
        resp.raise_for_status()


async def _create_ready_profile_photo(
    real_storage: StorageClient,
    user: User,
) -> Media:
    """Create a media record, upload a JPEG, process it, and return the ready Media."""
    media_id = uuid4()
    upload_key = f"pending/{media_id}/avatar.jpg"

    media = await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="avatar.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=upload_key,
    )

    jpeg_data = _make_jpeg(400, 400)
    presigned_url = await real_storage.generate_upload_url(upload_key, "image/jpeg", expires=300)
    await _upload_via_presigned_url(presigned_url, jpeg_data, "image/jpeg")

    media.status = MediaStatus.PROCESSING
    await media.save()

    with patch("app.media.worker._get_storage", return_value=real_storage):
        await process_media_job({}, str(media.id))

    await media.refresh_from_db()
    assert media.status == MediaStatus.READY
    return media


# ===========================================================================
# Happy paths
# ===========================================================================


async def test_full_registration_login_profile(client: httpx.AsyncClient) -> None:
    """Scenario 1: register -> login -> GET /users/me -> verify fields."""
    user_data = _user_data()

    # Register
    reg_resp = await client.post("/users/", json=user_data)
    assert reg_resp.status_code == 200

    # Login with same credentials
    login_resp = await client.post(
        "/users/token",
        json={"email": user_data["email"], "password": user_data["password"]},
    )
    assert login_resp.status_code == 200
    login_token = login_resp.json()["access_token"]

    # Fetch profile
    me = await client.get("/users/me", headers=_auth_header(login_token))
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == user_data["email"]
    assert body["phone"] == user_data["phone"]
    assert body["name"] == user_data["name"]
    assert body["surname"] == user_data["surname"]
    assert body["role"] == UserRole.USER
    assert body["profile_photo"] is None
    assert "id" in body
    assert "created_at" in body


async def test_profile_update(client: httpx.AsyncClient) -> None:
    """Scenario 2: update name, phone, email; verify changes persist."""
    _, token = await _register(client)

    patch_resp = await client.patch(
        "/users/me",
        json={"name": "Bob", "phone": "+79997654321", "email": "bob@example.com"},
        headers=_auth_header(token),
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["name"] == "Bob"
    assert updated["phone"] == "+79997654321"
    assert updated["email"] == "bob@example.com"

    # Verify persistence
    me = await client.get("/users/me", headers=_auth_header(token))
    assert me.status_code == 200
    assert me.json()["name"] == "Bob"
    assert me.json()["email"] == "bob@example.com"


async def test_password_change(client: httpx.AsyncClient) -> None:
    """Scenario 3: change password, login with new, confirm old fails."""
    _, token = await _register(client)

    new_password = "NewStrong1"
    patch_resp = await client.patch(
        "/users/me",
        json={"password": "StrongPass1", "new_password": new_password},
        headers=_auth_header(token),
    )
    assert patch_resp.status_code == 200

    # Login with new password
    login_resp = await client.post(
        "/users/token",
        json={"email": _USER_DATA["email"], "password": new_password},
    )
    assert login_resp.status_code == 200

    # Old password should fail
    old_login = await client.post(
        "/users/token",
        json={"email": _USER_DATA["email"], "password": "StrongPass1"},
    )
    assert old_login.status_code == 401


async def test_public_profile(client: httpx.AsyncClient) -> None:
    """Scenario 4: fetch user via GET /users/{id} without auth."""
    user, _token = await _register(client)
    user_id = user["id"]

    resp = await client.get(f"/users/{user_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == user_id
    assert body["name"] == _USER_DATA["name"]
    assert body["email"] == _USER_DATA["email"]


async def test_profile_photo_upload(
    client: httpx.AsyncClient,
    real_storage: StorageClient,
) -> None:
    """Scenario 5: register, upload photo via presigned URL, process, attach, verify."""
    user_read, token = await _register(client)

    db_user = await User.get(id=user_read["id"])
    media = await _create_ready_profile_photo(real_storage, db_user)

    try:
        # Attach via PATCH /users/me
        patch_resp = await client.patch(
            "/users/me",
            json={"profile_photo_id": str(media.id)},
            headers=_auth_header(token),
        )
        assert patch_resp.status_code == 200
        body = patch_resp.json()
        assert body["profile_photo"] is not None
        assert body["profile_photo"]["id"] == str(media.id)
        assert body["profile_photo"]["medium_url"]
        assert body["profile_photo"]["small_url"]

        # Also visible on /users/me
        me = await client.get("/users/me", headers=_auth_header(token))
        assert me.json()["profile_photo"]["id"] == str(media.id)
    finally:
        await real_storage.delete_prefix(f"pending/{media.id}/")
        await real_storage.delete_prefix(f"media/{media.id}/")


async def test_profile_photo_replacement(
    client: httpx.AsyncClient,
    real_storage: StorageClient,
) -> None:
    """Scenario 6: upload second photo, verify it replaces first."""
    user_read, token = await _register(client)
    db_user = await User.get(id=user_read["id"])

    photo1 = await _create_ready_profile_photo(real_storage, db_user)
    photo2 = await _create_ready_profile_photo(real_storage, db_user)

    try:
        # Attach first photo
        await client.patch(
            "/users/me",
            json={"profile_photo_id": str(photo1.id)},
            headers=_auth_header(token),
        )

        # Attach second photo (replaces first)
        resp = await client.patch(
            "/users/me",
            json={"profile_photo_id": str(photo2.id)},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["profile_photo"]["id"] == str(photo2.id)

        # Verify first photo is detached (no longer the profile photo)
        me = await client.get("/users/me", headers=_auth_header(token))
        assert me.json()["profile_photo"]["id"] == str(photo2.id)
    finally:
        for photo in (photo1, photo2):
            await real_storage.delete_prefix(f"pending/{photo.id}/")
            await real_storage.delete_prefix(f"media/{photo.id}/")


# ===========================================================================
# Negative / edge cases
# ===========================================================================


async def test_duplicate_email(client: httpx.AsyncClient) -> None:
    """Scenario 7: duplicate email -> 409."""
    await _register(client)
    resp = await client.post("/users/", json=_user_data())
    assert resp.status_code == 409


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("nouppercase1", "no uppercase"),
        ("NOLOWERCASE1", "no lowercase"),
        ("NoDigitsHere", "no digit"),
        ("Short1", "too short"),
    ],
    ids=["no_uppercase", "no_lowercase", "no_digit", "too_short"],
)
async def test_weak_passwords(client: httpx.AsyncClient, password: str, reason: str) -> None:
    """Scenario 8: weak passwords -> 422."""
    resp = await client.post("/users/", json=_user_data(password=password))
    assert resp.status_code == 422, f"Expected 422 for password with {reason}, got {resp.status_code}"


async def test_invalid_phone(client: httpx.AsyncClient) -> None:
    """Scenario 9: invalid phone -> 422."""
    resp = await client.post("/users/", json=_user_data(phone="123"))
    assert resp.status_code == 422

    resp2 = await client.post("/users/", json=_user_data(phone="not-a-phone"))
    assert resp2.status_code == 422


async def test_login_wrong_password(client: httpx.AsyncClient) -> None:
    """Scenario 10: login with wrong password -> 401."""
    await _register(client)
    resp = await client.post(
        "/users/token",
        json={"email": _USER_DATA["email"], "password": "WrongPass1"},
    )
    assert resp.status_code == 401


async def test_login_nonexistent_email(client: httpx.AsyncClient) -> None:
    """Scenario 11: login with non-existent email -> 401."""
    resp = await client.post(
        "/users/token",
        json={"email": "nobody@example.com", "password": "StrongPass1"},
    )
    assert resp.status_code == 401


async def test_expired_invalid_token(client: httpx.AsyncClient) -> None:
    """Scenario 12: expired/invalid token -> 401."""
    resp = await client.get("/users/me", headers=_auth_header("invalid.token.here"))
    assert resp.status_code == 401

    # Completely missing auth
    resp2 = await client.get("/users/me")
    assert resp2.status_code == 401


async def test_suspended_user_flow(client: httpx.AsyncClient) -> None:
    """Scenario 13: admin suspends user, user gets 403 on /users/me."""
    user, token = await _register(client)
    user_id = user["id"]

    # Suspend via direct DB update (simulating admin action)
    await User.filter(id=user_id).update(role=UserRole.SUSPENDED)

    # Suspended user should get 403 on authenticated endpoints
    me = await client.get("/users/me", headers=_auth_header(token))
    assert me.status_code == 403

    # Login should also fail with 403
    login_resp = await client.post(
        "/users/token",
        json={"email": _USER_DATA["email"], "password": "StrongPass1"},
    )
    assert login_resp.status_code == 403


async def test_upload_wrong_media_kind_for_profile(client: httpx.AsyncClient) -> None:
    """Scenario 14: upload video with user_profile context -> rejected.

    The user_profile context only makes sense for photos. When attaching,
    the service rejects non-photo media. We test via the request_upload_url
    endpoint using a video content type, which should still succeed at the
    upload URL stage. The rejection happens at attach time.
    """
    _, token = await _register(client)

    # Request upload URL for a video in user_profile context
    # This should succeed (upload URL creation doesn't validate context-kind pairing)
    upload_resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "video",
            "context": "user_profile",
            "filename": "video.mp4",
            "content_type": "video/mp4",
            "file_size": 1024,
        },
        headers=_auth_header(token),
    )
    # Upload URL creation may succeed; the real guard is at attach time
    if upload_resp.status_code == 200:
        media_id = upload_resp.json()["media_id"]
        # Try to attach this video as profile photo -> should fail
        # First mark it as ready so we can test the attach logic
        await Media.filter(id=media_id).update(
            status=MediaStatus.READY,
            variants={"full": "fake/key", "preview": "fake/key"},
        )
        patch_resp = await client.patch(
            "/users/me",
            json={"profile_photo_id": media_id},
            headers=_auth_header(token),
        )
        assert patch_resp.status_code == 400
    else:
        # If the upload URL endpoint rejects it, that's also valid
        assert upload_resp.status_code in (400, 422)


async def test_upload_confirm_by_another_user(client: httpx.AsyncClient) -> None:
    """Scenario 15: upload photo, another user tries to confirm -> 403."""
    _user1, token1 = await _register(client, email="user1@example.com")
    _user2, token2 = await _register(client, email="user2@example.com", phone="+79001112233")

    # User1 requests upload URL
    upload_resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers=_auth_header(token1),
    )
    assert upload_resp.status_code == 200
    media_id = upload_resp.json()["media_id"]

    # User2 tries to confirm user1's upload -> 403
    confirm_resp = await client.post(
        f"/media/{media_id}/confirm",
        headers=_auth_header(token2),
    )
    assert confirm_resp.status_code == 403


async def test_oversized_file_upload(client: httpx.AsyncClient) -> None:
    """Scenario 16: file exceeding max size -> rejected."""
    _user, token = await _register(client)

    settings = get_settings()
    max_photo_bytes = settings.media.max_photo_size_mb * 1024 * 1024
    oversized = max_photo_bytes + 1

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "huge.jpg",
            "content_type": "image/jpeg",
            "file_size": oversized,
        },
        headers=_auth_header(token),
    )
    assert resp.status_code == 400
