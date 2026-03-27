from typing import Any

from httpx import AsyncClient

from app.core.enums import ListingStatus
from app.listings.models import Listing, ListingCategory
from app.organizations.models import Organization
from app.users.models import User


class TestCreateCategory:
    async def test_create_category_success(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        resp = await client.post(
            f"/organizations/{org_id}/listings/categories/",
            json={"name": "Custom Category"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Custom Category"
        assert body["verified"] is False
        assert body["listing_count"] == 0

    async def test_create_category_requires_editor(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, _ = await create_organization()
        org_id = org_data["id"]
        resp = await client.post(
            f"/organizations/{org_id}/listings/categories/",
            json={"name": "Fail"},
        )
        assert resp.status_code == 401


class TestListPublicCategories:
    async def test_list_public_categories_only_verified(
        self,
        client: AsyncClient,
        seed_categories: list[ListingCategory],
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        # Create an unverified category
        await client.post(
            f"/organizations/{org_id}/listings/categories/",
            json={"name": "Unverified"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await client.get("/listings/categories/")
        assert resp.status_code == 200
        body = resp.json()
        names = [c["name"] for c in body]
        assert "Спецтехника" in names
        assert "Промышленное оборудование" in names
        assert "Unverified" not in names

    async def test_list_public_categories_ordered_by_count(
        self,
        client: AsyncClient,
        seed_categories: list[ListingCategory],
        verified_org: tuple[dict[str, Any], str],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        org = await Organization.get(id=org_id)
        user = await User.get(
            id=(await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})).json()["id"]
        )
        # Create 2 published listings in category 0, 1 in category 1
        for _ in range(2):
            await Listing.create(
                name="Item",
                category=seed_categories[0],
                price=100,
                status=ListingStatus.PUBLISHED,
                organization=org,
                added_by=user,
            )
        await Listing.create(
            name="Item2",
            category=seed_categories[1],
            price=100,
            status=ListingStatus.PUBLISHED,
            organization=org,
            added_by=user,
        )
        resp = await client.get("/listings/categories/")
        body = resp.json()
        assert body[0]["listing_count"] >= body[1]["listing_count"]


class TestListOrgCategories:
    async def test_list_org_categories_includes_global_and_org(
        self,
        client: AsyncClient,
        seed_categories: list[ListingCategory],
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        # Create org-specific category
        await client.post(
            f"/organizations/{org_id}/listings/categories/",
            json={"name": "Org Only"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Create a listing in the org category so it shows up
        org = await Organization.get(id=org_id)
        user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
        user = await User.get(id=user_resp.json()["id"])
        org_cat = await ListingCategory.filter(name="Org Only").first()
        await Listing.create(
            name="Item",
            category=org_cat,
            price=100,
            organization=org,
            added_by=user,
        )
        resp = await client.get(
            f"/organizations/{org_id}/listings/categories/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        names = [c["name"] for c in body]
        assert "Org Only" in names
        # Global verified categories should also be included
        assert "Спецтехника" in names

    async def test_list_org_categories_requires_membership(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, _ = await create_organization()
        org_id = org_data["id"]
        _, outsider_token = await create_user(email="outsider@example.com")
        resp = await client.get(
            f"/organizations/{org_id}/listings/categories/",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert resp.status_code == 403
