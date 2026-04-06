"""E2E tests for listing catalog, categories, and visibility rules.

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
    ListingStatus,
    MediaContext,
    MediaKind,
    MediaStatus,
    OrganizationStatus,
)
from app.listings.models import ListingCategory
from app.media.models import Media
from app.media.storage import StorageClient
from app.organizations.models import Organization
from app.users.models import User
from app.worker.media import process_media_job

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SBERBANK_INN = "7707083893"
YANDEX_INN = "7736207543"

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


async def _verify_org(org_id: str) -> None:
    await Organization.filter(id=org_id).update(status=OrganizationStatus.VERIFIED)


async def _create_verified_org(
    client: httpx.AsyncClient,
    token: str,
    **overrides: Any,
) -> dict[str, Any]:
    org = await _create_org(client, token, **overrides)
    await _verify_org(org["id"])
    return org


async def _create_global_category(name: str) -> ListingCategory:
    return await ListingCategory.create(name=name, verified=True)


async def _invite_and_accept_member(
    client: httpx.AsyncClient,
    org_id: str,
    admin_token: str,
    user_id: str,
    user_token: str,
    role: str = "editor",
) -> None:
    """Invite a user to an org and accept the invitation."""
    invite_resp = await client.post(
        f"/api/v1/organizations/{org_id}/members/invite",
        json={"user_id": user_id, "role": role},
        headers=_auth(admin_token),
    )
    assert invite_resp.status_code == 200, invite_resp.text
    member_id = invite_resp.json()["id"]

    accept_resp = await client.patch(
        f"/api/v1/organizations/{org_id}/members/{member_id}/accept",
        headers=_auth(user_token),
    )
    assert accept_resp.status_code == 200, accept_resp.text


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
    upload_key = f"pending/{media_id}/listing_photo.jpg"
    media = await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.LISTING,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="listing_photo.jpg",
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


async def _cleanup_media(real_storage: StorageClient, *media_items: Media) -> None:
    for m in media_items:
        await real_storage.delete_prefix(f"pending/{m.id}/")
        await real_storage.delete_prefix(f"media/{m.id}/")


# ===========================================================================
# Happy paths (1-13)
# ===========================================================================


async def test_create_listing(client: httpx.AsyncClient) -> None:
    """Scenario 1: editor creates listing, verify status=hidden and all fields."""
    user, token = await _register(client)
    org = await _create_verified_org(client, token)
    category = await _create_global_category("Спецтехника")

    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={
            "name": "Excavator CAT 320",
            "category_id": category.id,
            "price": 5000.0,
            "description": "Heavy excavator for rent",
            "specifications": {"weight": "20t", "year": "2023"},
            "with_operator": True,
            "on_owner_site": False,
            "delivery": True,
            "installation": False,
            "setup": True,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["name"] == "Excavator CAT 320"
    assert body["price"] == 5000.0
    assert body["description"] == "Heavy excavator for rent"
    assert body["specifications"] == {"weight": "20t", "year": "2023"}
    assert body["status"] == ListingStatus.HIDDEN
    assert body["organization_id"] == org["id"]
    assert body["added_by_id"] == user["id"]
    assert body["with_operator"] is True
    assert body["delivery"] is True
    assert body["setup"] is True
    assert body["on_owner_site"] is False
    assert body["installation"] is False
    assert body["category"]["id"] == category.id
    assert body["category"]["name"] == "Спецтехника"
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


async def test_update_listing(client: httpx.AsyncClient) -> None:
    """Scenario 2: update listing name, price, description, specs, booleans."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)
    category = await _create_global_category("Спецтехника")

    create_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Old Name", "category_id": category.id, "price": 1000.0},
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    listing_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}",
        json={
            "name": "New Name",
            "price": 2000.0,
            "description": "Updated description",
            "specifications": {"power": "100kW"},
            "with_operator": True,
            "delivery": True,
        },
        headers=_auth(token),
    )
    assert update_resp.status_code == 200, update_resp.text
    body = update_resp.json()
    assert body["name"] == "New Name"
    assert body["price"] == 2000.0
    assert body["description"] == "Updated description"
    assert body["specifications"] == {"power": "100kW"}
    assert body["with_operator"] is True
    assert body["delivery"] is True


async def test_publish_listing(client: httpx.AsyncClient) -> None:
    """Scenario 3: hidden -> published, appears in public catalog."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)
    category = await _create_global_category("Спецтехника")

    create_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Excavator", "category_id": category.id, "price": 5000.0},
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    listing_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == ListingStatus.HIDDEN

    # Publish
    status_resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
        json={"status": "published"},
        headers=_auth(token),
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == ListingStatus.PUBLISHED

    # Appears in public catalog
    catalog_resp = await client.get("/api/v1/listings/")
    assert catalog_resp.status_code == 200
    listings = catalog_resp.json()["items"]
    assert any(item["id"] == listing_id for item in listings)


async def test_hide_listing(client: httpx.AsyncClient) -> None:
    """Scenario 4: published -> hidden, disappears from catalog."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)
    category = await _create_global_category("Спецтехника")

    create_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Crane", "category_id": category.id, "price": 8000.0},
        headers=_auth(token),
    )
    listing_id = create_resp.json()["id"]

    # Publish first
    await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
        json={"status": "published"},
        headers=_auth(token),
    )

    # Hide
    hide_resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
        json={"status": "hidden"},
        headers=_auth(token),
    )
    assert hide_resp.status_code == 200
    assert hide_resp.json()["status"] == ListingStatus.HIDDEN

    # Disappears from public catalog
    catalog_resp = await client.get("/api/v1/listings/")
    listings = catalog_resp.json()["items"]
    assert not any(item["id"] == listing_id for item in listings)


async def test_archive_listing(client: httpx.AsyncClient) -> None:
    """Scenario 5: published -> archived, gone from catalog."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)
    category = await _create_global_category("Спецтехника")

    create_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Loader", "category_id": category.id, "price": 6000.0},
        headers=_auth(token),
    )
    listing_id = create_resp.json()["id"]

    # Publish then archive
    await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
        json={"status": "published"},
        headers=_auth(token),
    )
    archive_resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
        json={"status": "archived"},
        headers=_auth(token),
    )
    assert archive_resp.status_code == 200
    assert archive_resp.json()["status"] == ListingStatus.ARCHIVED

    catalog_resp = await client.get("/api/v1/listings/")
    listings = catalog_resp.json()["items"]
    assert not any(item["id"] == listing_id for item in listings)


async def test_delete_listing(client: httpx.AsyncClient) -> None:
    """Scenario 6: delete listing, verify 404 on fetch."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)
    category = await _create_global_category("Спецтехника")

    create_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Bulldozer", "category_id": category.id, "price": 7000.0},
        headers=_auth(token),
    )
    listing_id = create_resp.json()["id"]

    delete_resp = await client.delete(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}",
        headers=_auth(token),
    )
    assert delete_resp.status_code == 204

    # 404 on public fetch
    get_resp = await client.get(f"/api/v1/listings/{listing_id}")
    assert get_resp.status_code == 404


async def test_listing_with_media(
    client: httpx.AsyncClient,
    real_storage: StorageClient,
) -> None:
    """Scenario 7: create listing with photos, confirm processing, verify attached."""
    user_data, token = await _register(client)
    org = await _create_verified_org(client, token)
    category = await _create_global_category("Спецтехника")

    db_user = await User.get(id=user_data["id"])
    photo1 = await _create_ready_photo(real_storage, db_user)
    photo2 = await _create_ready_photo(real_storage, db_user)

    try:
        create_resp = await client.post(
            f"/api/v1/organizations/{org['id']}/listings/",
            json={
                "name": "Excavator with media",
                "category_id": category.id,
                "price": 5000.0,
                "photo_ids": [str(photo1.id), str(photo2.id)],
            },
            headers=_auth(token),
        )
        assert create_resp.status_code == 201, create_resp.text
        body = create_resp.json()
        assert len(body["photos"]) == 2
        photo_ids = {p["id"] for p in body["photos"]}
        assert str(photo1.id) in photo_ids
        assert str(photo2.id) in photo_ids
    finally:
        await _cleanup_media(real_storage, photo1, photo2)


async def test_update_listing_media(
    client: httpx.AsyncClient,
    real_storage: StorageClient,
) -> None:
    """Scenario 8: add photos to listing, then delete one."""
    user_data, token = await _register(client)
    org = await _create_verified_org(client, token)
    category = await _create_global_category("Спецтехника")

    db_user = await User.get(id=user_data["id"])
    photo1 = await _create_ready_photo(real_storage, db_user)
    photo2 = await _create_ready_photo(real_storage, db_user)

    try:
        # Create listing with two photos
        create_resp = await client.post(
            f"/api/v1/organizations/{org['id']}/listings/",
            json={
                "name": "Loader with photos",
                "category_id": category.id,
                "price": 3000.0,
                "photo_ids": [str(photo1.id), str(photo2.id)],
            },
            headers=_auth(token),
        )
        assert create_resp.status_code == 201
        listing_id = create_resp.json()["id"]
        assert len(create_resp.json()["photos"]) == 2

        # Update: keep only photo1
        update_resp = await client.patch(
            f"/api/v1/organizations/{org['id']}/listings/{listing_id}",
            json={"photo_ids": [str(photo1.id)]},
            headers=_auth(token),
        )
        assert update_resp.status_code == 200
        assert len(update_resp.json()["photos"]) == 1
        assert update_resp.json()["photos"][0]["id"] == str(photo1.id)
    finally:
        await _cleanup_media(real_storage, photo1, photo2)


async def test_create_org_specific_category(client: httpx.AsyncClient) -> None:
    """Scenario 9: create org-specific category, verified=false, visible in org list."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)

    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/categories/",
        json={"name": "Custom Equipment"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Custom Equipment"
    assert body["verified"] is False
    assert "id" in body

    # Create a published listing with this category so it shows in org categories
    cat_id = body["id"]
    listing_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Custom Item", "category_id": cat_id, "price": 1000.0},
        headers=_auth(token),
    )
    assert listing_resp.status_code == 201
    listing_id = listing_resp.json()["id"]
    await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
        json={"status": "published"},
        headers=_auth(token),
    )

    # Org category list should include it
    org_cats_resp = await client.get(
        f"/api/v1/organizations/{org['id']}/listings/categories/",
        headers=_auth(token),
    )
    assert org_cats_resp.status_code == 200
    org_cat_ids = [c["id"] for c in org_cats_resp.json()]
    assert cat_id in org_cat_ids


async def test_seed_categories_in_public_list(client: httpx.AsyncClient) -> None:
    """Scenario 10: global verified categories appear in public list, ordered by listing count."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)

    cat1 = await _create_global_category("Category A")
    cat2 = await _create_global_category("Category B")

    # Create 2 published listings in cat2, 1 in cat1
    for name in ("Item1", "Item2"):
        resp = await client.post(
            f"/api/v1/organizations/{org['id']}/listings/",
            json={"name": name, "category_id": cat2.id, "price": 1000.0},
            headers=_auth(token),
        )
        listing_id = resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
            json={"status": "published"},
            headers=_auth(token),
        )

    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Item3", "category_id": cat1.id, "price": 1000.0},
        headers=_auth(token),
    )
    listing_id = resp.json()["id"]
    await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
        json={"status": "published"},
        headers=_auth(token),
    )

    # Public categories: cat2 (2 listings) should come before cat1 (1 listing)
    public_cats_resp = await client.get("/api/v1/listings/categories/")
    assert public_cats_resp.status_code == 200
    cats = public_cats_resp.json()
    cat_ids = [c["id"] for c in cats]
    assert cat2.id in cat_ids
    assert cat1.id in cat_ids
    idx2 = cat_ids.index(cat2.id)
    idx1 = cat_ids.index(cat1.id)
    assert idx2 < idx1, "Category with more listings should come first"

    # Verify listing counts
    cat2_data = next(c for c in cats if c["id"] == cat2.id)
    cat1_data = next(c for c in cats if c["id"] == cat1.id)
    assert cat2_data["listing_count"] == 2
    assert cat1_data["listing_count"] == 1


async def test_org_category_list_includes_global_and_org_specific(client: httpx.AsyncClient) -> None:
    """Scenario 11: org category list includes both global and org-specific categories."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)

    global_cat = await _create_global_category("Global Category")

    # Create org-specific category
    org_cat_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/categories/",
        json={"name": "Org Category"},
        headers=_auth(token),
    )
    assert org_cat_resp.status_code == 201
    org_cat_id = org_cat_resp.json()["id"]

    # Create a published listing with each category so they appear in org list
    for cat_id in (global_cat.id, org_cat_id):
        resp = await client.post(
            f"/api/v1/organizations/{org['id']}/listings/",
            json={"name": f"Item-{cat_id}", "category_id": cat_id, "price": 1000.0},
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.text
        listing_id = resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
            json={"status": "published"},
            headers=_auth(token),
        )

    org_cats_resp = await client.get(
        f"/api/v1/organizations/{org['id']}/listings/categories/",
        headers=_auth(token),
    )
    assert org_cats_resp.status_code == 200
    cat_ids = [c["id"] for c in org_cats_resp.json()]
    assert global_cat.id in cat_ids
    assert org_cat_id in cat_ids


async def test_public_catalog_browsing(client: httpx.AsyncClient) -> None:
    """Scenario 12: multiple listings/orgs, filter by category_id and org_id."""
    # Create two users and two orgs
    _, token1 = await _register(client, email="org1@example.com")
    _, token2 = await _register(client, email="org2@example.com", phone="+79001112233")

    org1 = await _create_verified_org(client, token1, inn=SBERBANK_INN)
    org2 = await _create_verified_org(client, token2, inn=YANDEX_INN)

    cat_a = await _create_global_category("Category A")
    cat_b = await _create_global_category("Category B")

    # Org1: 1 listing in cat_a, 1 in cat_b
    for name, cat_id in [("O1-A", cat_a.id), ("O1-B", cat_b.id)]:
        resp = await client.post(
            f"/api/v1/organizations/{org1['id']}/listings/",
            json={"name": name, "category_id": cat_id, "price": 1000.0},
            headers=_auth(token1),
        )
        listing_id = resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org1['id']}/listings/{listing_id}/status",
            json={"status": "published"},
            headers=_auth(token1),
        )

    # Org2: 1 listing in cat_a
    resp = await client.post(
        f"/api/v1/organizations/{org2['id']}/listings/",
        json={"name": "O2-A", "category_id": cat_a.id, "price": 2000.0},
        headers=_auth(token2),
    )
    listing_id = resp.json()["id"]
    await client.patch(
        f"/api/v1/organizations/{org2['id']}/listings/{listing_id}/status",
        json={"status": "published"},
        headers=_auth(token2),
    )

    # All listings
    all_resp = await client.get("/api/v1/listings/")
    assert all_resp.status_code == 200
    assert len(all_resp.json()) == 3

    # Filter by category_a
    cat_a_resp = await client.get(f"/api/v1/listings/?category_id={cat_a.id}")
    assert cat_a_resp.status_code == 200
    cat_a_listings = cat_a_resp.json()["items"]
    assert len(cat_a_listings) == 2
    assert all(item["category"]["id"] == cat_a.id for item in cat_a_listings)

    # Filter by org2
    org2_resp = await client.get(f"/api/v1/listings/?organization_id={org2['id']}")
    assert org2_resp.status_code == 200
    org2_listings = org2_resp.json()["items"]
    assert len(org2_listings) == 1
    assert org2_listings[0]["organization_id"] == org2["id"]

    # Filter by both category_a + org1
    combined_resp = await client.get(
        f"/api/v1/listings/?category_id={cat_a.id}&organization_id={org1['id']}",
    )
    assert combined_resp.status_code == 200
    combined = combined_resp.json()["items"]
    assert len(combined) == 1
    assert combined[0]["name"] == "O1-A"


async def test_public_catalog_property_filters(client: httpx.AsyncClient) -> None:
    """Filter public listings by boolean properties and price range."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)
    cat = await _create_global_category("Filter Cat")

    # Create 3 listings with different properties
    listings_data = [
        {"name": "Cheap+Delivery", "price": 500.0, "delivery": True, "with_operator": False},
        {"name": "Mid+Operator", "price": 1500.0, "delivery": False, "with_operator": True},
        {"name": "Expensive+Both", "price": 3000.0, "delivery": True, "with_operator": True},
    ]
    for data in listings_data:
        resp = await client.post(
            f"/api/v1/organizations/{org['id']}/listings/",
            json={"category_id": cat.id, **data},
            headers=_auth(token),
        )
        listing_id = resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
            json={"status": "published"},
            headers=_auth(token),
        )

    # Filter by delivery=true
    resp = await client.get("/api/v1/listings/?delivery=true")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert all(i["delivery"] is True for i in items)

    # Filter by with_operator=true
    resp = await client.get("/api/v1/listings/?with_operator=true")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert all(i["with_operator"] is True for i in items)

    # Filter by delivery=false
    resp = await client.get("/api/v1/listings/?delivery=false")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Mid+Operator"

    # Price range: 1000-2000
    resp = await client.get("/api/v1/listings/?price_min=1000&price_max=2000")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Mid+Operator"

    # Price min only
    resp = await client.get("/api/v1/listings/?price_min=1500")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    names = {i["name"] for i in items}
    assert names == {"Mid+Operator", "Expensive+Both"}

    # Combined: delivery + price range
    resp = await client.get("/api/v1/listings/?delivery=true&price_min=1000")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Expensive+Both"


async def test_public_catalog_multi_category_filter(client: httpx.AsyncClient) -> None:
    """Filter public listings by multiple category_id query params."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)

    cat_a = await _create_global_category("Multi-A")
    cat_b = await _create_global_category("Multi-B")
    cat_c = await _create_global_category("Multi-C")

    # Create one published listing per category
    for name, cat_id in [("L-A", cat_a.id), ("L-B", cat_b.id), ("L-C", cat_c.id)]:
        resp = await client.post(
            f"/api/v1/organizations/{org['id']}/listings/",
            json={"name": name, "category_id": cat_id, "price": 1000.0},
            headers=_auth(token),
        )
        listing_id = resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
            json={"status": "published"},
            headers=_auth(token),
        )

    # Filter by two categories (repeated query param)
    resp = await client.get(
        "/api/v1/listings/",
        params=[("category_id", cat_a.id), ("category_id", cat_b.id)],
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    returned_names = {item["name"] for item in items}
    assert returned_names == {"L-A", "L-B"}

    # Single category still works
    resp = await client.get("/api/v1/listings/", params=[("category_id", cat_c.id)])
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["name"] == "L-C"

    # No category filter returns all
    resp = await client.get("/api/v1/listings/")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3


async def test_listing_detail_public_access(client: httpx.AsyncClient) -> None:
    """Scenario 13: published listing from verified org, no auth needed."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)
    category = await _create_global_category("Спецтехника")

    create_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={
            "name": "Public Excavator",
            "category_id": category.id,
            "price": 5000.0,
            "description": "Available for rent",
        },
        headers=_auth(token),
    )
    listing_id = create_resp.json()["id"]

    await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
        json={"status": "published"},
        headers=_auth(token),
    )

    # Fetch without auth
    detail_resp = await client.get(f"/api/v1/listings/{listing_id}")
    assert detail_resp.status_code == 200
    body = detail_resp.json()
    assert body["id"] == listing_id
    assert body["name"] == "Public Excavator"
    assert body["description"] == "Available for rent"
    assert body["status"] == ListingStatus.PUBLISHED


# ===========================================================================
# Negative / edge cases (14-25)
# ===========================================================================


async def test_non_member_creates_listing(client: httpx.AsyncClient) -> None:
    """Scenario 14: non-member creates listing -> 403."""
    _, creator_token = await _register(client, email="creator@example.com")
    _, outsider_token = await _register(client, email="outsider@example.com", phone="+79001112233")

    org = await _create_verified_org(client, creator_token)
    category = await _create_global_category("Спецтехника")

    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Illegal Listing", "category_id": category.id, "price": 1000.0},
        headers=_auth(outsider_token),
    )
    assert resp.status_code == 403


async def test_viewer_creates_listing(client: httpx.AsyncClient) -> None:
    """Scenario 15: viewer creates listing -> 403."""
    _, admin_token = await _register(client, email="admin@example.com")
    viewer_data, viewer_token = await _register(client, email="viewer@example.com", phone="+79001112233")

    org = await _create_verified_org(client, admin_token)
    category = await _create_global_category("Спецтехника")

    # Invite viewer
    await _invite_and_accept_member(
        client,
        org["id"],
        admin_token,
        viewer_data["id"],
        viewer_token,
        role="viewer",
    )

    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Viewer Listing", "category_id": category.id, "price": 1000.0},
        headers=_auth(viewer_token),
    )
    assert resp.status_code == 403


async def test_listing_in_unverified_org_not_public(client: httpx.AsyncClient) -> None:
    """Scenario 16: create listing in unverified org succeeds, not visible publicly."""
    _, token = await _register(client)
    org = await _create_org(client, token)  # Not verified
    category = await _create_global_category("Спецтехника")

    create_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Hidden Org Item", "category_id": category.id, "price": 1000.0},
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    listing_id = create_resp.json()["id"]

    # Publish it
    await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
        json={"status": "published"},
        headers=_auth(token),
    )

    # Should not appear in public catalog
    catalog_resp = await client.get("/api/v1/listings/")
    assert catalog_resp.status_code == 200
    assert not any(item["id"] == listing_id for item in catalog_resp.json()["items"])


async def test_non_member_views_listing_from_unverified_org(client: httpx.AsyncClient) -> None:
    """Scenario 17: non-member views listing from unverified org -> 403."""
    _, creator_token = await _register(client, email="creator@example.com")
    _, outsider_token = await _register(client, email="outsider@example.com", phone="+79001112233")

    org = await _create_org(client, creator_token)  # Not verified
    category = await _create_global_category("Спецтехника")

    create_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Secret Item", "category_id": category.id, "price": 1000.0},
        headers=_auth(creator_token),
    )
    listing_id = create_resp.json()["id"]

    # Non-member tries to view -> 403
    detail_resp = await client.get(
        f"/api/v1/listings/{listing_id}",
        headers=_auth(outsider_token),
    )
    assert detail_resp.status_code == 403


async def test_member_views_listing_from_unverified_org(client: httpx.AsyncClient) -> None:
    """Scenario 18: member views listing from unverified org -> succeeds."""
    _, creator_token = await _register(client)
    org = await _create_org(client, creator_token)  # Not verified
    category = await _create_global_category("Спецтехника")

    create_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Internal Item", "category_id": category.id, "price": 1000.0},
        headers=_auth(creator_token),
    )
    listing_id = create_resp.json()["id"]

    # Creator is a member, should be able to view
    detail_resp = await client.get(
        f"/api/v1/listings/{listing_id}",
        headers=_auth(creator_token),
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == listing_id


async def test_create_listing_nonexistent_category(client: httpx.AsyncClient) -> None:
    """Scenario 19: create listing with non-existent category -> error."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)

    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Bad Category Item", "category_id": "NOCAT1", "price": 1000.0},
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_update_listing_from_another_org(client: httpx.AsyncClient) -> None:
    """Scenario 20: update listing from another org -> 403."""
    _, token1 = await _register(client, email="org1@example.com")
    _, token2 = await _register(client, email="org2@example.com", phone="+79001112233")

    org1 = await _create_verified_org(client, token1, inn=SBERBANK_INN)
    org2 = await _create_verified_org(client, token2, inn=YANDEX_INN)
    category = await _create_global_category("Спецтехника")

    # Create listing in org1
    create_resp = await client.post(
        f"/api/v1/organizations/{org1['id']}/listings/",
        json={"name": "Org1 Item", "category_id": category.id, "price": 1000.0},
        headers=_auth(token1),
    )
    listing_id = create_resp.json()["id"]

    # Token2 (org2 editor) tries to update org1's listing via org2 route
    resp = await client.patch(
        f"/api/v1/organizations/{org2['id']}/listings/{listing_id}",
        json={"name": "Hacked Name"},
        headers=_auth(token2),
    )
    assert resp.status_code == 404  # listing not found in org2


async def test_delete_listing_from_another_org(client: httpx.AsyncClient) -> None:
    """Scenario 21: delete listing from another org -> 403."""
    _, token1 = await _register(client, email="org1@example.com")
    _, token2 = await _register(client, email="org2@example.com", phone="+79001112233")

    org1 = await _create_verified_org(client, token1, inn=SBERBANK_INN)
    org2 = await _create_verified_org(client, token2, inn=YANDEX_INN)
    category = await _create_global_category("Спецтехника")

    create_resp = await client.post(
        f"/api/v1/organizations/{org1['id']}/listings/",
        json={"name": "Org1 Item", "category_id": category.id, "price": 1000.0},
        headers=_auth(token1),
    )
    listing_id = create_resp.json()["id"]

    # Token2 tries to delete org1's listing via org2 route
    resp = await client.delete(
        f"/api/v1/organizations/{org2['id']}/listings/{listing_id}",
        headers=_auth(token2),
    )
    assert resp.status_code == 404  # listing not found in org2


async def test_status_change_by_viewer(client: httpx.AsyncClient) -> None:
    """Scenario 22: status change by viewer -> 403."""
    _, admin_token = await _register(client, email="admin@example.com")
    viewer_data, viewer_token = await _register(client, email="viewer@example.com", phone="+79001112233")

    org = await _create_verified_org(client, admin_token)
    category = await _create_global_category("Спецтехника")

    # Invite viewer
    await _invite_and_accept_member(
        client,
        org["id"],
        admin_token,
        viewer_data["id"],
        viewer_token,
        role="viewer",
    )

    create_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Item", "category_id": category.id, "price": 1000.0},
        headers=_auth(admin_token),
    )
    listing_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
        json={"status": "published"},
        headers=_auth(viewer_token),
    )
    assert resp.status_code == 403


async def test_public_catalog_excludes_hidden_archived(client: httpx.AsyncClient) -> None:
    """Scenario 23: public catalog excludes hidden and archived listings."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)
    category = await _create_global_category("Спецтехника")

    listing_ids: dict[str, str] = {}
    for name in ("Published Item", "Hidden Item", "Archived Item"):
        resp = await client.post(
            f"/api/v1/organizations/{org['id']}/listings/",
            json={"name": name, "category_id": category.id, "price": 1000.0},
            headers=_auth(token),
        )
        listing_ids[name] = resp.json()["id"]

    # Publish all first
    for lid in listing_ids.values():
        await client.patch(
            f"/api/v1/organizations/{org['id']}/listings/{lid}/status",
            json={"status": "published"},
            headers=_auth(token),
        )

    # Hide one
    await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_ids['Hidden Item']}/status",
        json={"status": "hidden"},
        headers=_auth(token),
    )

    # Archive another
    await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_ids['Archived Item']}/status",
        json={"status": "archived"},
        headers=_auth(token),
    )

    catalog_resp = await client.get("/api/v1/listings/")
    assert catalog_resp.status_code == 200
    catalog_ids = [item["id"] for item in catalog_resp.json()["items"]]
    assert listing_ids["Published Item"] in catalog_ids
    assert listing_ids["Hidden Item"] not in catalog_ids
    assert listing_ids["Archived Item"] not in catalog_ids


async def test_create_category_by_viewer(client: httpx.AsyncClient) -> None:
    """Scenario 24: create category by viewer -> 403."""
    _, admin_token = await _register(client, email="admin@example.com")
    viewer_data, viewer_token = await _register(client, email="viewer@example.com", phone="+79001112233")

    org = await _create_verified_org(client, admin_token)

    await _invite_and_accept_member(
        client,
        org["id"],
        admin_token,
        viewer_data["id"],
        viewer_token,
        role="viewer",
    )

    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/categories/",
        json={"name": "Viewer Category"},
        headers=_auth(viewer_token),
    )
    assert resp.status_code == 403


async def test_public_category_list_excludes_unverified(client: httpx.AsyncClient) -> None:
    """Scenario 25: public category list excludes unverified categories."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)

    # Create a global verified category
    global_cat = await _create_global_category("Global Verified")

    # Create an org-specific unverified category
    org_cat_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/categories/",
        json={"name": "Org Unverified"},
        headers=_auth(token),
    )
    assert org_cat_resp.status_code == 201
    org_cat_id = org_cat_resp.json()["id"]

    # Public list should include global verified, exclude unverified
    public_resp = await client.get("/api/v1/listings/categories/")
    assert public_resp.status_code == 200
    public_cat_ids = [c["id"] for c in public_resp.json()]
    assert global_cat.id in public_cat_ids
    assert org_cat_id not in public_cat_ids


async def test_org_categories_public_no_auth(client: httpx.AsyncClient) -> None:
    """Scenario 26: org categories are accessible without authentication."""
    _, token = await _register(client)
    org = await _create_verified_org(client, token)

    await _create_global_category("Public Category")

    # Create org-specific category with a published listing
    cat_resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/categories/",
        json={"name": "Org Category"},
        headers=_auth(token),
    )
    assert cat_resp.status_code == 201
    cat_id = cat_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/organizations/{org['id']}/listings/",
        json={"name": "Item", "category_id": cat_id, "price": 1000.0},
        headers=_auth(token),
    )
    listing_id = resp.json()["id"]
    await client.patch(
        f"/api/v1/organizations/{org['id']}/listings/{listing_id}/status",
        json={"status": "published"},
        headers=_auth(token),
    )

    # No auth header
    resp = await client.get(f"/api/v1/organizations/{org['id']}/listings/categories/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = [c["name"] for c in body]
    assert "Org Category" in names
    # Global category with no published listings should NOT appear
    assert "Public Category" not in names


async def test_org_categories_nonexistent_org_404(client: httpx.AsyncClient) -> None:
    """Scenario 27: org categories for non-existent org returns 404."""
    resp = await client.get("/api/v1/organizations/NOORG1/listings/categories/")
    assert resp.status_code == 404
