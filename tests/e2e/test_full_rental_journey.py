"""E2E mega-test: full platform lifecycle from registration to order completion.

Walks through 21 steps covering user registration, org setup, listing management,
and multiple order scenarios in one continuous story.

Uses real infrastructure: PostgreSQL, MinIO, Redis, Dadata API.
Only ``datetime.now`` is mocked for auto-transition scenarios.
"""

import datetime
import io
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from app.core.config import get_settings
from app.core.enums import (
    ListingStatus,
    MediaContext,
    MediaKind,
    MediaStatus,
    MembershipRole,
    MembershipStatus,
    OrderStatus,
    OrganizationStatus,
    UserRole,
)
from app.listings.models import Listing, ListingCategory
from app.media.models import Media
from app.media.storage import StorageClient
from app.media.worker import process_media_job
from app.users.models import User

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


async def _create_ready_photo(
    real_storage: StorageClient,
    user: User,
    *,
    context: MediaContext = MediaContext.USER_PROFILE,
    filename: str = "avatar.jpg",
) -> Media:
    """Create a media record, upload a JPEG, process it, and return the ready Media."""
    media_id = uuid4()
    upload_key = f"pending/{media_id}/{filename}"
    media = await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=context,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename=filename,
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
    with patch("app.media.worker._get_storage", return_value=real_storage):
        await process_media_job({}, str(media.id))
    await media.refresh_from_db()
    assert media.status == MediaStatus.READY
    return media


def _today() -> datetime.date:
    return datetime.datetime.now(tz=datetime.UTC).date()


def _future_dates(days_ahead: int = 10, duration: int = 5) -> tuple[str, str]:
    start = _today() + datetime.timedelta(days=days_ahead)
    end = start + datetime.timedelta(days=duration - 1)
    return start.isoformat(), end.isoformat()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture
def mock_today() -> Generator[MagicMock]:
    """Patch ``datetime.now`` in the orders service to return a controllable datetime."""
    real_datetime = datetime.datetime
    with patch("app.orders.service.datetime") as mock_dt:
        mock_dt.now.return_value = real_datetime.now(tz=datetime.UTC)
        mock_dt.side_effect = real_datetime
        mock_dt.UTC = datetime.UTC
        yield mock_dt


# ---------------------------------------------------------------------------
# The mega test
# ---------------------------------------------------------------------------


async def test_full_rental_journey(
    client: httpx.AsyncClient,
    real_storage: StorageClient,
    mock_today: MagicMock,
) -> None:
    """Walk through the ENTIRE platform lifecycle in 21 steps.

    1.  Renter registers (with profile photo)
    2.  Org owner registers
    3.  Org owner creates organization (real Dadata)
    4.  Org owner adds payment details
    5.  Org owner uploads org profile photo
    6.  Platform admin verifies org
    7.  Org owner invites an editor; editor registers and accepts
    8.  Editor creates a category for the org
    9.  Editor creates a listing with photos
    10. Editor publishes the listing
    11. Renter browses public catalog, finds listing, views detail
    12. Renter places an order (verify estimated cost)
    13. Editor offers adjusted terms
    14. Renter confirms the offer
    15. Mock date to start -> order active, listing in_rent
    16. Verify listing shows in_rent
    17. Mock date past end -> order finished, listing published
    18. Renter places second order
    19. Org editor rejects second order
    20. Renter places third order, org offers, renter declines
    21. Verify final state
    """
    uploaded_media: list[Media] = []

    try:
        # ==================================================================
        # Step 1: Renter registers with profile photo
        # ==================================================================
        renter_data, renter_token = await _register(
            client,
            email="renter@example.com",
            phone="+79001112233",
            name="Арсений",
            surname="Арендатор",
        )
        renter_id = renter_data["id"]

        db_renter = await User.get(id=renter_id)
        renter_photo = await _create_ready_photo(real_storage, db_renter, context=MediaContext.USER_PROFILE)
        uploaded_media.append(renter_photo)

        patch_resp = await client.patch(
            "/api/v1/users/me",
            json={"profile_photo_id": str(renter_photo.id)},
            headers=_auth(renter_token),
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["profile_photo"] is not None
        assert patch_resp.json()["profile_photo"]["id"] == str(renter_photo.id)

        # ==================================================================
        # Step 2: Org owner registers
        # ==================================================================
        owner_data, owner_token = await _register(
            client,
            email="owner@example.com",
            phone="+79002223344",
            name="Олег",
            surname="Владелец",
        )
        owner_id = owner_data["id"]

        # ==================================================================
        # Step 3: Org owner creates organization (real Dadata, adds contacts)
        # ==================================================================
        org_resp = await client.post(
            "/api/v1/organizations/",
            json={
                "inn": SBERBANK_INN,
                "contacts": [
                    {
                        "display_name": "Олег Владелец",
                        "phone": "+79002223344",
                        "email": "owner@example.com",
                    },
                ],
            },
            headers=_auth(owner_token),
        )
        assert org_resp.status_code == 200, org_resp.text
        org = org_resp.json()
        org_id: str = org["id"]
        assert org["status"] == OrganizationStatus.CREATED
        assert org["inn"] == SBERBANK_INN
        assert org["short_name"] is not None  # Dadata filled it
        assert len(org["contacts"]) == 1

        # ==================================================================
        # Step 4: Org owner adds payment details
        # ==================================================================
        pay_resp = await client.post(
            f"/api/v1/organizations/{org_id}/payment-details",
            json=_PAYMENT_DETAILS,
            headers=_auth(owner_token),
        )
        assert pay_resp.status_code == 200
        assert pay_resp.json()["payment_account"] == _PAYMENT_DETAILS["payment_account"]

        # ==================================================================
        # Step 5: Org owner uploads org profile photo
        # ==================================================================
        db_owner = await User.get(id=owner_id)
        org_photo = await _create_ready_photo(
            real_storage,
            db_owner,
            context=MediaContext.ORG_PROFILE,
            filename="org_avatar.jpg",
        )
        uploaded_media.append(org_photo)

        photo_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/photo",
            json={"photo_id": str(org_photo.id)},
            headers=_auth(owner_token),
        )
        assert photo_resp.status_code == 200
        assert photo_resp.json()["photo"] is not None
        assert photo_resp.json()["photo"]["id"] == str(org_photo.id)

        # ==================================================================
        # Step 6: Platform admin verifies org
        # ==================================================================
        admin_data, admin_token = await _register(
            client,
            email="admin@example.com",
            phone="+79003334455",
            name="Админ",
            surname="Платформы",
        )
        await User.filter(id=admin_data["id"]).update(role=UserRole.ADMIN)

        verify_resp = await client.patch(
            f"/api/v1/private/organizations/{org_id}/verify",
            headers=_auth(admin_token),
        )
        assert verify_resp.status_code == 200
        assert verify_resp.json()["status"] == OrganizationStatus.VERIFIED

        # ==================================================================
        # Step 7: Org owner invites an editor; editor registers and accepts
        # ==================================================================
        editor_data, editor_token = await _register(
            client,
            email="editor@example.com",
            phone="+79004445566",
            name="Елена",
            surname="Редактор",
        )
        editor_id = editor_data["id"]

        invite_resp = await client.post(
            f"/api/v1/organizations/{org_id}/members/invite",
            json={"user_id": editor_id, "role": MembershipRole.EDITOR},
            headers=_auth(owner_token),
        )
        assert invite_resp.status_code == 200
        membership = invite_resp.json()
        assert membership["status"] == MembershipStatus.INVITED
        assert membership["role"] == MembershipRole.EDITOR
        membership_id = membership["id"]

        accept_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/members/{membership_id}/accept",
            headers=_auth(editor_token),
        )
        assert accept_resp.status_code == 200
        assert accept_resp.json()["status"] == MembershipStatus.MEMBER

        # ==================================================================
        # Step 8: Editor creates a category for the org
        # ==================================================================
        # Use a global verified category (same pattern as other tests)
        category = await ListingCategory.create(name="Спецтехника", verified=True)

        # ==================================================================
        # Step 9: Editor creates a listing with photos
        # ==================================================================
        listing_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={
                "name": "Excavator CAT 320",
                "category_id": category.id,
                "price": 1000.0,
                "description": "Heavy excavator for rent",
                "specifications": {"weight": "20t", "year": "2023"},
                "with_operator": True,
                "delivery": True,
            },
            headers=_auth(editor_token),
        )
        assert listing_resp.status_code == 201, listing_resp.text
        listing = listing_resp.json()
        listing_id: str = listing["id"]
        assert listing["status"] == ListingStatus.HIDDEN
        assert listing["added_by_id"] == editor_id

        # Attach a listing photo
        listing_photo = await _create_ready_photo(
            real_storage,
            await User.get(id=editor_id),
            context=MediaContext.LISTING,
            filename="listing_photo.jpg",
        )
        uploaded_media.append(listing_photo)

        attach_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}",
            json={"photo_ids": [str(listing_photo.id)]},
            headers=_auth(editor_token),
        )
        assert attach_resp.status_code == 200

        # ==================================================================
        # Step 10: Editor publishes the listing -> verify in public catalog
        # ==================================================================
        publish_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers=_auth(editor_token),
        )
        assert publish_resp.status_code == 200
        assert publish_resp.json()["status"] == ListingStatus.PUBLISHED

        catalog_resp = await client.get("/api/v1/listings/")
        assert catalog_resp.status_code == 200
        catalog_ids = [item["id"] for item in catalog_resp.json()["items"]]
        assert listing_id in catalog_ids

        # ==================================================================
        # Step 11: Renter browses public catalog, finds listing, views detail
        # ==================================================================
        detail_resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == listing_id
        assert detail["name"] == "Excavator CAT 320"
        assert detail["price"] == 1000.0
        assert detail["status"] == ListingStatus.PUBLISHED

        # ==================================================================
        # Step 12: Renter places an order (verify estimated cost)
        # ==================================================================
        start_str, end_str = _future_dates(days_ahead=10, duration=5)

        order_resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start_str,
                "requested_end_date": end_str,
            },
            headers=_auth(renter_token),
        )
        assert order_resp.status_code == 201, order_resp.text
        order1 = order_resp.json()
        order1_id: str = order1["id"]
        assert order1["status"] == OrderStatus.PENDING
        # 5 days * 1000/day = 5000
        assert order1["estimated_cost"] == "5000.00"

        # ==================================================================
        # Step 13: Editor offers adjusted terms
        # ==================================================================
        offer_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order1_id}/offer",
            json={
                "offered_cost": "4500.00",
                "offered_start_date": start_str,
                "offered_end_date": end_str,
            },
            headers=_auth(editor_token),
        )
        assert offer_resp.status_code == 200
        assert offer_resp.json()["status"] == OrderStatus.OFFERED
        assert offer_resp.json()["offered_cost"] == "4500.00"

        # ==================================================================
        # Step 14: Renter confirms the offer
        # ==================================================================
        confirm_resp = await client.patch(
            f"/api/v1/orders/{order1_id}/confirm",
            headers=_auth(renter_token),
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["status"] == OrderStatus.CONFIRMED

        # ==================================================================
        # Step 15: Mock date to start -> order active, listing in_rent
        # ==================================================================
        start_date = datetime.date.fromisoformat(start_str)
        mock_today.now.return_value = datetime.datetime(
            start_date.year, start_date.month, start_date.day, tzinfo=datetime.UTC
        )

        get_order_resp = await client.get(f"/api/v1/orders/{order1_id}", headers=_auth(renter_token))
        assert get_order_resp.status_code == 200
        assert get_order_resp.json()["status"] == OrderStatus.ACTIVE

        # ==================================================================
        # Step 16: Verify listing shows in_rent
        # ==================================================================
        listing_obj = await Listing.get(id=listing_id)
        assert listing_obj.status == ListingStatus.IN_RENT

        # ==================================================================
        # Step 17: Mock date past end -> order finished, listing published
        # ==================================================================
        end_date = datetime.date.fromisoformat(end_str)
        past_end = end_date + datetime.timedelta(days=1)
        mock_today.now.return_value = datetime.datetime(
            past_end.year, past_end.month, past_end.day, tzinfo=datetime.UTC
        )

        get_finished_resp = await client.get(f"/api/v1/orders/{order1_id}", headers=_auth(renter_token))
        assert get_finished_resp.status_code == 200
        assert get_finished_resp.json()["status"] == OrderStatus.FINISHED

        listing_after = await Listing.get(id=listing_id)
        assert listing_after.status == ListingStatus.PUBLISHED

        # ==================================================================
        # Step 18: Renter places second order (listing is published again)
        # ==================================================================
        # Reset mock to real time so dates validate properly
        mock_today.now.return_value = datetime.datetime.now(tz=datetime.UTC)

        start2_str, end2_str = _future_dates(days_ahead=20, duration=3)

        order2_resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start2_str,
                "requested_end_date": end2_str,
            },
            headers=_auth(renter_token),
        )
        assert order2_resp.status_code == 201, order2_resp.text
        order2 = order2_resp.json()
        order2_id: str = order2["id"]
        assert order2["status"] == OrderStatus.PENDING

        # ==================================================================
        # Step 19: Org editor rejects second order
        # ==================================================================
        reject_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order2_id}/reject",
            headers=_auth(editor_token),
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == OrderStatus.REJECTED

        # ==================================================================
        # Step 20: Renter places third order, org offers, renter declines
        # ==================================================================
        start3_str, end3_str = _future_dates(days_ahead=30, duration=4)

        order3_resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start3_str,
                "requested_end_date": end3_str,
            },
            headers=_auth(renter_token),
        )
        assert order3_resp.status_code == 201, order3_resp.text
        order3 = order3_resp.json()
        order3_id: str = order3["id"]
        assert order3["status"] == OrderStatus.PENDING

        # Org offers
        offer3_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order3_id}/offer",
            json={
                "offered_cost": "3500.00",
                "offered_start_date": start3_str,
                "offered_end_date": end3_str,
            },
            headers=_auth(editor_token),
        )
        assert offer3_resp.status_code == 200
        assert offer3_resp.json()["status"] == OrderStatus.OFFERED

        # Renter declines
        decline_resp = await client.patch(
            f"/api/v1/orders/{order3_id}/decline",
            headers=_auth(renter_token),
        )
        assert decline_resp.status_code == 200
        assert decline_resp.json()["status"] == OrderStatus.DECLINED

        # ==================================================================
        # Step 21: Verify final state
        # ==================================================================

        # All orders in expected statuses
        my_orders_resp = await client.get("/api/v1/orders/", headers=_auth(renter_token))
        assert my_orders_resp.status_code == 200
        my_orders = my_orders_resp.json()["items"]
        assert len(my_orders) == 3

        order_statuses = {o["id"]: o["status"] for o in my_orders}
        assert order_statuses[order1_id] == OrderStatus.FINISHED
        assert order_statuses[order2_id] == OrderStatus.REJECTED
        assert order_statuses[order3_id] == OrderStatus.DECLINED

        # Listing is published (available for new orders)
        final_listing = await Listing.get(id=listing_id)
        assert final_listing.status == ListingStatus.PUBLISHED

        # Members are correct
        members_resp = await client.get(
            f"/api/v1/organizations/{org_id}/members",
            headers=_auth(owner_token),
        )
        assert members_resp.status_code == 200
        members = members_resp.json()["items"]
        assert len(members) == 2
        member_roles = {m["user_id"]: m["role"] for m in members}
        assert member_roles[owner_id] == MembershipRole.ADMIN
        assert member_roles[editor_id] == MembershipRole.EDITOR

    finally:
        # Cleanup uploaded media from storage
        for media in uploaded_media:
            await real_storage.delete_prefix(f"pending/{media.id}/")
            await real_storage.delete_prefix(f"media/{media.id}/")
