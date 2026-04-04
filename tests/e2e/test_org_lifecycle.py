"""E2E tests for organization lifecycle, membership management, contacts, and payments.

Uses real infrastructure: PostgreSQL, MinIO, Redis, Dadata API.
"""

import io
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from app.core.config import get_settings
from app.core.enums import (
    MediaContext,
    MediaKind,
    MediaStatus,
    MembershipRole,
    MembershipStatus,
    OrganizationStatus,
    UserRole,
)
from app.media.models import Media
from app.media.storage import StorageClient
from app.users.models import User
from app.worker.media import process_media_job

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SBERBANK_INN = "7707083893"

_PAYMENT_DETAILS: dict[str, str] = {
    "payment_account": "40702810938000060425",
    "bank_bic": "044525225",
    "bank_inn": "7707083893",
    "bank_name": "ПАО Сбербанк",
    "bank_correspondent_account": "30101810400000000225",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_jpeg(width: int = 400, height: int = 400) -> bytes:
    img = Image.new("RGB", (width, height), color=(0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


async def _register(client: httpx.AsyncClient, **overrides: Any) -> tuple[dict[str, Any], str]:
    defaults: dict[str, Any] = {
        "email": "user@example.com",
        "password": "StrongPass1",
        "phone": "+79991234567",
        "name": "Иван",
        "surname": "Иванов",
    }
    defaults.update(overrides)
    resp = await client.post("/api/v1/users/", json=defaults)
    assert resp.status_code == 200, resp.text
    token: str = resp.json()["access_token"]
    me = await client.get("/api/v1/users/me", headers=_auth(token))
    assert me.status_code == 200, me.text
    return me.json(), token


def _org_payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "inn": SBERBANK_INN,
        "contacts": [
            {
                "display_name": "Иван Иванов",
                "phone": "+79991234567",
                "email": "contact@example.com",
            },
        ],
    }
    data.update(overrides)
    return data


async def _create_org(
    client: httpx.AsyncClient,
    token: str,
    **overrides: Any,
) -> dict[str, Any]:
    payload = _org_payload(**overrides)
    resp = await client.post("/api/v1/organizations/", json=payload, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    result: dict[str, Any] = resp.json()
    return result


@pytest.fixture
async def real_storage() -> StorageClient:
    settings = get_settings()
    storage = StorageClient(
        endpoint_url=settings.storage.endpoint_url,
        presigned_endpoint_url=settings.storage.presigned_endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        bucket=settings.storage.bucket,
    )
    await storage.ensure_bucket()
    return storage


async def _create_ready_photo(real_storage: StorageClient, user: User) -> Media:
    media_id = uuid4()
    upload_key = f"pending/{media_id}/avatar.jpg"
    media = await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.ORG_PROFILE,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="avatar.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=upload_key,
    )
    jpeg_data = _make_jpeg()
    presigned_url = await real_storage.generate_upload_url(upload_key, "image/jpeg", expires=300)
    async with httpx.AsyncClient() as c:
        resp = await c.put(presigned_url, content=jpeg_data, headers={"Content-Type": "image/jpeg"})
        resp.raise_for_status()
    media.status = MediaStatus.PROCESSING
    await media.save()
    with patch("app.worker.media._get_storage", return_value=real_storage):
        await process_media_job({}, str(media.id))
    await media.refresh_from_db()
    assert media.status == MediaStatus.READY
    return media


async def _make_platform_admin(user_id: str) -> None:
    await User.filter(id=user_id).update(role=UserRole.ADMIN)


# ===========================================================================
# Happy paths (1-13)
# ===========================================================================


async def test_create_organization(client: httpx.AsyncClient) -> None:
    """Scenario 1: create org with INN + contacts, Dadata fills legal data, creator is admin member."""
    user, token = await _register(client)

    org = await _create_org(client, token)

    assert org["status"] == OrganizationStatus.CREATED
    assert org["inn"] == SBERBANK_INN
    assert org["short_name"] is not None
    assert org["full_name"] is not None
    assert len(org["contacts"]) == 1
    assert org["contacts"][0]["display_name"] == "Иван Иванов"

    # Verify creator is admin member
    members_resp = await client.get(f"/api/v1/organizations/{org['id']}/members", headers=_auth(token))
    assert members_resp.status_code == 200
    members = members_resp.json()["items"]
    assert len(members) == 1
    assert members[0]["user_id"] == user["id"]
    assert members[0]["role"] == MembershipRole.ADMIN
    assert members[0]["status"] == MembershipStatus.MEMBER


async def test_org_profile_photo(client: httpx.AsyncClient, real_storage: StorageClient) -> None:
    """Scenario 2: upload and attach org profile photo."""
    user_read, token = await _register(client)
    org = await _create_org(client, token)

    db_user = await User.get(id=user_read["id"])
    media = await _create_ready_photo(real_storage, db_user)

    try:
        resp = await client.patch(
            f"/api/v1/organizations/{org['id']}/photo",
            json={"photo_id": str(media.id)},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["photo"] is not None
        assert body["photo"]["id"] == str(media.id)

        # Photo visible via GET
        get_resp = await client.get(f"/api/v1/organizations/{org['id']}")
        assert get_resp.status_code == 200
        assert get_resp.json()["photo"]["id"] == str(media.id)
    finally:
        await real_storage.delete_prefix(f"pending/{media.id}/")
        await real_storage.delete_prefix(f"media/{media.id}/")


async def test_update_contacts(client: httpx.AsyncClient) -> None:
    """Scenario 3: PUT new contacts, verify old replaced."""
    _, token = await _register(client)
    org = await _create_org(client, token)

    new_contacts = {
        "contacts": [
            {"display_name": "New Person", "phone": "+79001112233"},
            {"display_name": "Another Person", "email": "another@example.com"},
        ],
    }
    resp = await client.put(
        f"/api/v1/organizations/{org['id']}/contacts",
        json=new_contacts,
        headers=_auth(token),
    )
    assert resp.status_code == 200
    contacts = resp.json()
    assert len(contacts) == 2
    names = {c["display_name"] for c in contacts}
    assert names == {"New Person", "Another Person"}

    # Verify via GET org
    get_resp = await client.get(f"/api/v1/organizations/{org['id']}")
    assert len(get_resp.json()["contacts"]) == 2


async def test_add_payment_details(client: httpx.AsyncClient) -> None:
    """Scenario 4: POST payment details, verify via GET."""
    _, token = await _register(client)
    org = await _create_org(client, token)

    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/payment-details",
        json=_PAYMENT_DETAILS,
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["payment_account"] == _PAYMENT_DETAILS["payment_account"]
    assert body["bank_name"] == _PAYMENT_DETAILS["bank_name"]

    get_resp = await client.get(
        f"/api/v1/organizations/{org['id']}/payment-details",
        headers=_auth(token),
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["payment_account"] == _PAYMENT_DETAILS["payment_account"]


async def test_update_payment_details(client: httpx.AsyncClient) -> None:
    """Scenario 5: POST payment details twice (upsert)."""
    _, token = await _register(client)
    org = await _create_org(client, token)

    await client.post(
        f"/api/v1/organizations/{org['id']}/payment-details",
        json=_PAYMENT_DETAILS,
        headers=_auth(token),
    )

    updated = {**_PAYMENT_DETAILS, "bank_name": "АО Тинькофф Банк"}
    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/payment-details",
        json=updated,
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["bank_name"] == "АО Тинькофф Банк"
    # Same ID (upsert, not duplicate)
    get_resp = await client.get(
        f"/api/v1/organizations/{org['id']}/payment-details",
        headers=_auth(token),
    )
    assert get_resp.json()["bank_name"] == "АО Тинькофф Банк"


async def test_platform_admin_verifies_org(client: httpx.AsyncClient) -> None:
    """Scenario 6: platform admin verifies org, status becomes verified."""
    _, token = await _register(client)
    org = await _create_org(client, token)
    assert org["status"] == OrganizationStatus.CREATED

    admin_user, admin_token = await _register(client, email="admin@example.com", phone="+79001112233")
    await _make_platform_admin(admin_user["id"])

    resp = await client.patch(
        f"/api/v1/private/organizations/{org['id']}/verify",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == OrganizationStatus.VERIFIED


async def test_full_setup_journey(client: httpx.AsyncClient, real_storage: StorageClient) -> None:
    """Scenario 7: create -> photo -> contacts -> payments -> verify."""
    user_read, token = await _register(client)
    org = await _create_org(client, token)
    org_id = org["id"]

    # Photo
    db_user = await User.get(id=user_read["id"])
    media = await _create_ready_photo(real_storage, db_user)
    try:
        photo_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/photo",
            json={"photo_id": str(media.id)},
            headers=_auth(token),
        )
        assert photo_resp.status_code == 200

        # Contacts
        contacts_resp = await client.put(
            f"/api/v1/organizations/{org_id}/contacts",
            json={"contacts": [{"display_name": "Updated Contact", "phone": "+79001112233"}]},
            headers=_auth(token),
        )
        assert contacts_resp.status_code == 200

        # Payment details
        pay_resp = await client.post(
            f"/api/v1/organizations/{org_id}/payment-details",
            json=_PAYMENT_DETAILS,
            headers=_auth(token),
        )
        assert pay_resp.status_code == 200

        # Verify
        admin_user, admin_token = await _register(client, email="admin@example.com", phone="+79002223344")
        await _make_platform_admin(admin_user["id"])
        verify_resp = await client.patch(
            f"/api/v1/private/organizations/{org_id}/verify",
            headers=_auth(admin_token),
        )
        assert verify_resp.status_code == 200
        final = verify_resp.json()
        assert final["status"] == OrganizationStatus.VERIFIED
        assert final["photo"] is not None
    finally:
        await real_storage.delete_prefix(f"pending/{media.id}/")
        await real_storage.delete_prefix(f"media/{media.id}/")


async def test_invite_member(client: httpx.AsyncClient) -> None:
    """Scenario 8: admin invites user with editor role, user accepts -> member+editor."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    invitee, invitee_token = await _register(client, email="invitee@example.com", phone="+79001112233")

    invite_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": invitee["id"], "role": MembershipRole.EDITOR},
        headers=_auth(admin_token),
    )
    assert invite_resp.status_code == 200
    membership = invite_resp.json()
    assert membership["status"] == MembershipStatus.INVITED
    assert membership["role"] == MembershipRole.EDITOR

    # User accepts
    accept_resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}/accept",
        headers=_auth(invitee_token),
    )
    assert accept_resp.status_code == 200
    accepted = accept_resp.json()
    assert accepted["status"] == MembershipStatus.MEMBER
    assert accepted["role"] == MembershipRole.EDITOR


async def test_join_request(client: httpx.AsyncClient) -> None:
    """Scenario 9: user sends join -> candidate, admin approves with viewer -> member."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    _, joiner_token = await _register(client, email="joiner@example.com", phone="+79001112233")

    join_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/members/join",
        headers=_auth(joiner_token),
    )
    assert join_resp.status_code == 200
    membership = join_resp.json()
    assert membership["status"] == MembershipStatus.CANDIDATE

    # Admin approves with viewer role
    approve_resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}/approve",
        json={"role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    assert approve_resp.status_code == 200
    approved = approve_resp.json()
    assert approved["status"] == MembershipStatus.MEMBER
    assert approved["role"] == MembershipRole.VIEWER


async def test_change_member_role(client: httpx.AsyncClient) -> None:
    """Scenario 10: admin changes viewer -> editor."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    invitee, invitee_token = await _register(client, email="member@example.com", phone="+79001112233")

    # Invite as viewer
    invite_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": invitee["id"], "role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    membership = invite_resp.json()
    # Accept
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}/accept",
        headers=_auth(invitee_token),
    )

    # Change role to editor
    role_resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}/role",
        json={"role": MembershipRole.EDITOR},
        headers=_auth(admin_token),
    )
    assert role_resp.status_code == 200
    assert role_resp.json()["role"] == MembershipRole.EDITOR


async def test_remove_member_by_admin(client: httpx.AsyncClient) -> None:
    """Scenario 11: admin removes a member, they lose access."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    invitee, invitee_token = await _register(client, email="member@example.com", phone="+79001112233")

    invite_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": invitee["id"], "role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    membership = invite_resp.json()
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}/accept",
        headers=_auth(invitee_token),
    )

    # Admin removes member
    del_resp = await client.delete(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}",
        headers=_auth(admin_token),
    )
    assert del_resp.status_code == 204

    # Removed user cannot list members anymore
    members_resp = await client.get(
        f"/api/v1/organizations/{org['id']}/members",
        headers=_auth(invitee_token),
    )
    assert members_resp.status_code == 403


async def test_member_leaves_voluntarily(client: httpx.AsyncClient) -> None:
    """Scenario 12: member self-removes via DELETE."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    invitee, invitee_token = await _register(client, email="member@example.com", phone="+79001112233")

    invite_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": invitee["id"], "role": MembershipRole.EDITOR},
        headers=_auth(admin_token),
    )
    membership = invite_resp.json()
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}/accept",
        headers=_auth(invitee_token),
    )

    # Member leaves
    del_resp = await client.delete(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}",
        headers=_auth(invitee_token),
    )
    assert del_resp.status_code == 204

    # Verify they're no longer a member
    members_resp = await client.get(
        f"/api/v1/organizations/{org['id']}/members",
        headers=_auth(admin_token),
    )
    assert members_resp.status_code == 200
    member_ids = [m["user_id"] for m in members_resp.json()["items"]]
    assert invitee["id"] not in member_ids


async def test_list_members(client: httpx.AsyncClient) -> None:
    """Scenario 13: create org with multiple members, verify list."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    user2, token2 = await _register(client, email="u2@example.com", phone="+79001112233")
    user3, token3 = await _register(client, email="u3@example.com", phone="+79002223344")

    # Invite user2
    inv2 = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": user2["id"], "role": MembershipRole.EDITOR},
        headers=_auth(admin_token),
    )
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{inv2.json()['id']}/accept",
        headers=_auth(token2),
    )

    # Invite user3
    inv3 = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": user3["id"], "role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{inv3.json()['id']}/accept",
        headers=_auth(token3),
    )

    # List members
    resp = await client.get(f"/api/v1/organizations/{org['id']}/members", headers=_auth(admin_token))
    assert resp.status_code == 200
    members = resp.json()["items"]
    assert len(members) == 3
    roles = {m["role"] for m in members}
    assert roles == {MembershipRole.ADMIN, MembershipRole.EDITOR, MembershipRole.VIEWER}


# ===========================================================================
# Negative / edge cases (14-32)
# ===========================================================================


async def test_duplicate_inn(client: httpx.AsyncClient) -> None:
    """Scenario 14: duplicate INN -> 409."""
    _, token = await _register(client)
    await _create_org(client, token)

    _, token2 = await _register(client, email="u2@example.com", phone="+79001112233")
    resp = await client.post(
        "/api/v1/organizations/",
        json=_org_payload(),
        headers=_auth(token2),
    )
    assert resp.status_code == 409


async def test_invalid_inn_format(client: httpx.AsyncClient) -> None:
    """Scenario 15: invalid INN format -> 422."""
    _, token = await _register(client)

    # Too short
    resp = await client.post("/api/v1/organizations/", json=_org_payload(inn="12345"), headers=_auth(token))
    assert resp.status_code == 422

    # Non-digit
    resp2 = await client.post("/api/v1/organizations/", json=_org_payload(inn="abcdefghij"), headers=_auth(token))
    assert resp2.status_code == 422


async def test_missing_contacts_on_creation(client: httpx.AsyncClient) -> None:
    """Scenario 16: missing contacts on creation -> 422."""
    _, token = await _register(client)

    resp = await client.post(
        "/api/v1/organizations/",
        json={"inn": SBERBANK_INN, "contacts": []},
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_invalid_contact_no_phone_email(client: httpx.AsyncClient) -> None:
    """Scenario 17: contact with neither phone nor email -> 422."""
    _, token = await _register(client)

    resp = await client.post(
        "/api/v1/organizations/",
        json={
            "inn": SBERBANK_INN,
            "contacts": [{"display_name": "No Contact Info"}],
        },
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_non_authenticated_creates_org(client: httpx.AsyncClient) -> None:
    """Scenario 18: no auth -> 401."""
    resp = await client.post("/api/v1/organizations/", json=_org_payload())
    assert resp.status_code == 401


async def test_non_admin_tries_to_verify(client: httpx.AsyncClient) -> None:
    """Scenario 19: non-platform-admin tries to verify -> 403."""
    _, token = await _register(client)
    org = await _create_org(client, token)

    resp = await client.patch(
        f"/api/v1/private/organizations/{org['id']}/verify",
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_non_admin_updates_contacts(client: httpx.AsyncClient) -> None:
    """Scenario 20: non-admin member updates contacts -> 403."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    viewer, viewer_token = await _register(client, email="viewer@example.com", phone="+79001112233")
    inv = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": viewer["id"], "role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{inv.json()['id']}/accept",
        headers=_auth(viewer_token),
    )

    resp = await client.put(
        f"/api/v1/organizations/{org['id']}/contacts",
        json={"contacts": [{"display_name": "Hacker", "phone": "+79001112233"}]},
        headers=_auth(viewer_token),
    )
    assert resp.status_code == 403


async def test_non_admin_adds_payment_details(client: httpx.AsyncClient) -> None:
    """Scenario 21: non-admin adds payment details -> 403."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    viewer, viewer_token = await _register(client, email="viewer@example.com", phone="+79001112233")
    inv = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": viewer["id"], "role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{inv.json()['id']}/accept",
        headers=_auth(viewer_token),
    )

    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/payment-details",
        json=_PAYMENT_DETAILS,
        headers=_auth(viewer_token),
    )
    assert resp.status_code == 403


async def test_org_photo_by_non_admin(client: httpx.AsyncClient, real_storage: StorageClient) -> None:
    """Scenario 22: non-admin attaches org photo -> 403."""
    admin_read, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    viewer, viewer_token = await _register(client, email="viewer@example.com", phone="+79001112233")
    inv = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": viewer["id"], "role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{inv.json()['id']}/accept",
        headers=_auth(viewer_token),
    )

    db_user = await User.get(id=admin_read["id"])
    media = await _create_ready_photo(real_storage, db_user)

    try:
        resp = await client.patch(
            f"/api/v1/organizations/{org['id']}/photo",
            json={"photo_id": str(media.id)},
            headers=_auth(viewer_token),
        )
        assert resp.status_code == 403
    finally:
        await real_storage.delete_prefix(f"pending/{media.id}/")
        await real_storage.delete_prefix(f"media/{media.id}/")


async def test_payment_details_when_none_set(client: httpx.AsyncClient) -> None:
    """Scenario 23: GET payment details when none exist -> 404."""
    _, token = await _register(client)
    org = await _create_org(client, token)

    resp = await client.get(
        f"/api/v1/organizations/{org['id']}/payment-details",
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_unverified_org_listing_visibility(client: httpx.AsyncClient) -> None:
    """Scenario 24: non-member cannot access unverified org's members -> 403."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    _, outsider_token = await _register(client, email="outsider@example.com", phone="+79001112233")

    # Non-member trying to list members -> 403
    resp = await client.get(
        f"/api/v1/organizations/{org['id']}/members",
        headers=_auth(outsider_token),
    )
    assert resp.status_code == 403


async def test_editor_tries_to_invite(client: httpx.AsyncClient) -> None:
    """Scenario 25: editor tries to invite -> 403."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    editor, editor_token = await _register(client, email="editor@example.com", phone="+79001112233")
    inv = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": editor["id"], "role": MembershipRole.EDITOR},
        headers=_auth(admin_token),
    )
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{inv.json()['id']}/accept",
        headers=_auth(editor_token),
    )

    target, _ = await _register(client, email="target@example.com", phone="+79002223344")
    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": target["id"], "role": MembershipRole.VIEWER},
        headers=_auth(editor_token),
    )
    assert resp.status_code == 403


async def test_viewer_tries_to_approve_candidate(client: httpx.AsyncClient) -> None:
    """Scenario 26: viewer tries to approve candidate -> 403."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    viewer, viewer_token = await _register(client, email="viewer@example.com", phone="+79001112233")
    inv = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": viewer["id"], "role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{inv.json()['id']}/accept",
        headers=_auth(viewer_token),
    )

    # Another user joins as candidate
    _, joiner_token = await _register(client, email="joiner@example.com", phone="+79002223344")
    join_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/members/join",
        headers=_auth(joiner_token),
    )
    candidate_id = join_resp.json()["id"]

    # Viewer tries to approve
    resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{candidate_id}/approve",
        json={"role": MembershipRole.VIEWER},
        headers=_auth(viewer_token),
    )
    assert resp.status_code == 403


async def test_invite_already_member_user(client: httpx.AsyncClient) -> None:
    """Scenario 27: invite user who is already a member -> 409."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    member, member_token = await _register(client, email="member@example.com", phone="+79001112233")
    inv = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": member["id"], "role": MembershipRole.EDITOR},
        headers=_auth(admin_token),
    )
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{inv.json()['id']}/accept",
        headers=_auth(member_token),
    )

    # Try to invite again
    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": member["id"], "role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 409


async def test_user_accepts_invite_meant_for_someone_else(client: httpx.AsyncClient) -> None:
    """Scenario 28: user accepts invite meant for another user -> 403."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    invitee, _ = await _register(client, email="invitee@example.com", phone="+79001112233")
    _, imposter_token = await _register(client, email="imposter@example.com", phone="+79002223344")

    inv = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": invitee["id"], "role": MembershipRole.EDITOR},
        headers=_auth(admin_token),
    )
    membership_id = inv.json()["id"]

    # Imposter tries to accept
    resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership_id}/accept",
        headers=_auth(imposter_token),
    )
    assert resp.status_code == 403


async def test_approve_non_candidate_status(client: httpx.AsyncClient) -> None:
    """Scenario 29: try to approve a member who is not a candidate -> 400."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    invitee, invitee_token = await _register(client, email="invitee@example.com", phone="+79001112233")
    inv = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": invitee["id"], "role": MembershipRole.EDITOR},
        headers=_auth(admin_token),
    )
    membership = inv.json()
    # Accept first
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}/accept",
        headers=_auth(invitee_token),
    )

    # Try to approve an already-member
    resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}/approve",
        json={"role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400


async def test_accept_non_invited_status(client: httpx.AsyncClient) -> None:
    """Scenario 30: try to accept a membership that is not invited -> 400."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    _, joiner_token = await _register(client, email="joiner@example.com", phone="+79001112233")
    join_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/members/join",
        headers=_auth(joiner_token),
    )
    candidate_membership = join_resp.json()

    # Try to accept a candidate membership (should fail, it's not invited)
    resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{candidate_membership['id']}/accept",
        headers=_auth(joiner_token),
    )
    assert resp.status_code == 400


async def test_non_admin_changes_member_role(client: httpx.AsyncClient) -> None:
    """Scenario 31: non-admin changes member role -> 403."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    editor, editor_token = await _register(client, email="editor@example.com", phone="+79001112233")
    inv = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": editor["id"], "role": MembershipRole.EDITOR},
        headers=_auth(admin_token),
    )
    membership = inv.json()
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}/accept",
        headers=_auth(editor_token),
    )

    viewer, viewer_token = await _register(client, email="viewer@example.com", phone="+79002223344")
    inv2 = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": viewer["id"], "role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    membership2 = inv2.json()
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership2['id']}/accept",
        headers=_auth(viewer_token),
    )

    # Editor tries to change viewer's role
    resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership2['id']}/role",
        json={"role": MembershipRole.EDITOR},
        headers=_auth(editor_token),
    )
    assert resp.status_code == 403


async def test_non_admin_removes_another_member(client: httpx.AsyncClient) -> None:
    """Scenario 32: non-admin removes another member -> 403."""
    _, admin_token = await _register(client, email="orgadmin@example.com")
    org = await _create_org(client, admin_token)

    editor, editor_token = await _register(client, email="editor@example.com", phone="+79001112233")
    inv = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": editor["id"], "role": MembershipRole.EDITOR},
        headers=_auth(admin_token),
    )
    membership = inv.json()
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership['id']}/accept",
        headers=_auth(editor_token),
    )

    viewer, viewer_token = await _register(client, email="viewer@example.com", phone="+79002223344")
    inv2 = await client.post(
        f"/api/v1/organizations/{org['id']}/members/invite",
        json={"user_id": viewer["id"], "role": MembershipRole.VIEWER},
        headers=_auth(admin_token),
    )
    membership2 = inv2.json()
    await client.patch(
        f"/api/v1/organizations/{org['id']}/members/{membership2['id']}/accept",
        headers=_auth(viewer_token),
    )

    # Editor tries to remove viewer
    resp = await client.delete(
        f"/api/v1/organizations/{org['id']}/members/{membership2['id']}",
        headers=_auth(editor_token),
    )
    assert resp.status_code == 403
