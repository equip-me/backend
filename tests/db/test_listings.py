from typing import Any

from httpx import AsyncClient

from app.listings.models import ListingCategory


class TestCreateCategory:
    async def test_create_category_success(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/categories/",
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
            f"/api/v1/organizations/{org_id}/listings/categories/",
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
            f"/api/v1/organizations/{org_id}/listings/categories/",
            json={"name": "Unverified"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await client.get("/api/v1/listings/categories/")
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
        headers = {"Authorization": f"Bearer {token}"}
        # Create 2 published listings in category 0, 1 in category 1
        for _ in range(2):
            create_resp = await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": "Item", "category_id": seed_categories[0].id, "price": 100.0},
                headers=headers,
            )
            listing_id = create_resp.json()["id"]
            await client.patch(
                f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
                json={"status": "published"},
                headers=headers,
            )
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Item2", "category_id": seed_categories[1].id, "price": 100.0},
            headers=headers,
        )
        listing_id = create_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers=headers,
        )
        resp = await client.get("/api/v1/listings/categories/")
        body = resp.json()
        assert body[0]["listing_count"] >= body[1]["listing_count"]


class TestListOrgCategories:
    async def test_list_org_categories_only_published(
        self,
        client: AsyncClient,
        seed_categories: list[ListingCategory],
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        headers = {"Authorization": f"Bearer {token}"}
        # Create org-specific category with a published listing
        cat_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/categories/",
            json={"name": "Published Cat"},
            headers=headers,
        )
        pub_cat_id = cat_resp.json()["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Item", "category_id": pub_cat_id, "price": 100.0},
            headers=headers,
        )
        listing_id = resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers=headers,
        )

        # Create another category with only a hidden listing (should NOT appear)
        cat_resp2 = await client.post(
            f"/api/v1/organizations/{org_id}/listings/categories/",
            json={"name": "Hidden Cat"},
            headers=headers,
        )
        hidden_cat_id = cat_resp2.json()["id"]
        await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Hidden Item", "category_id": hidden_cat_id, "price": 50.0},
            headers=headers,
        )

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/categories/",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        names = [c["name"] for c in body]
        assert "Published Cat" in names
        assert "Hidden Cat" not in names
        # Global categories with no published listings should NOT appear
        assert "Спецтехника" not in names
        # Check listing count
        pub_entry = next(c for c in body if c["name"] == "Published Cat")
        assert pub_entry["listing_count"] == 1

    async def test_list_org_categories_no_auth(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, _ = await create_organization()
        org_id = org_data["id"]
        resp = await client.get(f"/api/v1/organizations/{org_id}/listings/categories/")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        # No published listings, so empty
        assert len(body) == 0

    async def test_list_org_categories_nonexistent_org(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.get("/api/v1/organizations/NOORG1/listings/categories/")
        assert resp.status_code == 404


class TestListAvailableCategories:
    async def test_returns_verified_and_org_categories(
        self,
        client: AsyncClient,
        seed_categories: list[ListingCategory],
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        headers = {"Authorization": f"Bearer {token}"}
        # Create an org-specific category (unverified)
        await client.post(
            f"/api/v1/organizations/{org_id}/listings/categories/",
            json={"name": "Org Custom"},
            headers=headers,
        )
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/categories/available/",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        names = [c["name"] for c in body]
        # Verified seed categories present
        assert "Спецтехника" in names
        assert "Промышленное оборудование" in names
        # Org-owned unverified category present
        assert "Org Custom" in names

    async def test_excludes_other_org_categories(
        self,
        client: AsyncClient,
        seed_categories: list[ListingCategory],
        create_organization: Any,
        create_user: Any,
    ) -> None:
        # Org A creates a category
        org_a_data, token_a = await create_organization()
        org_a_id = org_a_data["id"]
        await client.post(
            f"/api/v1/organizations/{org_a_id}/listings/categories/",
            json={"name": "Org A Only"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        # Org B should not see Org A's category
        _, token_b = await create_user(email="orgb@example.com")
        org_b_data, token_b = await create_organization(token=token_b, inn="5001012345")
        org_b_id = org_b_data["id"]
        resp = await client.get(
            f"/api/v1/organizations/{org_b_id}/listings/categories/available/",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()]
        assert "Org A Only" not in names

    async def test_requires_auth(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, _ = await create_organization()
        org_id = org_data["id"]
        resp = await client.get(f"/api/v1/organizations/{org_id}/listings/categories/available/")
        assert resp.status_code == 401

    async def test_requires_membership(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, _ = await create_organization()
        org_id = org_data["id"]
        _, outsider_token = await create_user(email="outsider@example.com")
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/categories/available/",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert resp.status_code == 403

    async def test_includes_categories_with_zero_listings(
        self,
        client: AsyncClient,
        seed_categories: list[ListingCategory],
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        headers = {"Authorization": f"Bearer {token}"}
        # Create category but no listings
        await client.post(
            f"/api/v1/organizations/{org_id}/listings/categories/",
            json={"name": "Empty Cat"},
            headers=headers,
        )
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/categories/available/",
            headers=headers,
        )
        body = resp.json()
        empty_cat = next(c for c in body if c["name"] == "Empty Cat")
        assert empty_cat["listing_count"] == 0


class TestCreateListing:
    async def test_create_listing_success(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={
                "name": "Excavator",
                "category_id": seed_categories[0].id,
                "price": 5000.0,
                "description": "Heavy duty excavator",
                "with_operator": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Excavator"
        assert body["price"] == 5000.0
        assert body["status"] == "hidden"
        assert body["with_operator"] is True
        assert body["delivery"] is False
        assert body["category"]["id"] == seed_categories[0].id
        assert body["organization_id"] == org_id

    async def test_create_listing_invalid_category(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={
                "name": "Item",
                "category_id": "BADCAT",
                "price": 100.0,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    async def test_create_listing_other_org_category_rejected(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        # Org A creates a category
        org_a_data, token_a = await create_organization()
        org_a_id = org_a_data["id"]
        cat_resp = await client.post(
            f"/api/v1/organizations/{org_a_id}/listings/categories/",
            json={"name": "Org A Only"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        cat_id = cat_resp.json()["id"]
        # Org B tries to use that category
        _, token_b = await create_user(email="orgb@example.com")
        org_b_data, token_b = await create_organization(token=token_b, inn="5001012345")
        org_b_id = org_b_data["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_b_id}/listings/",
            json={
                "name": "Item",
                "category_id": cat_id,
                "price": 100.0,
            },
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 404

    async def test_create_listing_requires_editor(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, _ = await create_organization()
        org_id = org_data["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={
                "name": "Item",
                "category_id": "AAAAAA",
                "price": 100.0,
            },
        )
        assert resp.status_code == 401

    async def test_create_listing_missing_required_fields(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"description": "Missing name, category, price"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


class TestUpdateListing:
    async def test_update_listing_partial(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Old Name", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}",
            json={"name": "New Name"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"
        assert resp.json()["price"] == 100.0  # unchanged

    async def test_update_listing_change_category(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}",
            json={"category_id": seed_categories[1].id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["category"]["id"] == seed_categories[1].id

    async def test_update_listing_not_found(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/listings/BADID1",
            json={"name": "Nope"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


class TestDeleteListing:
    async def test_delete_listing_success(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "To Delete", "category_id": seed_categories[0].id, "price": 50.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        resp = await client.delete(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204
        # Verify deletion via HTTP — updating deleted listing should return 404
        get_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}",
            json={"name": "Should Fail"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_resp.status_code == 404

    async def test_delete_listing_not_found(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        resp = await client.delete(
            f"/api/v1/organizations/{org_id}/listings/BADID1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


class TestChangeListingStatus:
    async def test_change_status_to_published(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "published"

    async def test_change_status_to_archived(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "archived"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

    async def test_change_status_requires_editor(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
        create_user: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        _, outsider_token = await create_user(email="outsider@example.com")
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert resp.status_code == 403


class TestListOrgListings:
    async def test_list_org_listings_all_statuses(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        for name, status in [("Hidden", "hidden"), ("Published", "published"), ("Archived", "archived")]:
            create_resp = await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": name, "category_id": seed_categories[0].id, "price": 100.0},
                headers={"Authorization": f"Bearer {token}"},
            )
            listing_id = create_resp.json()["id"]
            if status != "hidden":
                await client.patch(
                    f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
                    json={"status": status},
                    headers={"Authorization": f"Bearer {token}"},
                )
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 3

    async def test_list_org_listings_requires_membership(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, _ = await create_organization()
        org_id = org_data["id"]
        _, outsider_token = await create_user(email="outsider@example.com")
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert resp.status_code == 403


class TestListOrgListingsFilters:
    async def test_filter_by_search(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        headers = {"Authorization": f"Bearer {token}"}
        for name in ["Excavator CAT", "Crane Liebherr", "Bulldozer"]:
            await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": name, "category_id": seed_categories[0].id, "price": 100.0},
                headers=headers,
            )
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/?search=Excavator",
            headers=headers,
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Excavator CAT"

    async def test_filter_by_category(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        headers = {"Authorization": f"Bearer {token}"}
        await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Cat0 Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers=headers,
        )
        await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Cat1 Item", "category_id": seed_categories[1].id, "price": 200.0},
            headers=headers,
        )
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/?category_id={seed_categories[0].id}",
            headers=headers,
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Cat0 Item"

    async def test_filter_by_price_range(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        headers = {"Authorization": f"Bearer {token}"}
        await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Cheap", "category_id": seed_categories[0].id, "price": 50.0},
            headers=headers,
        )
        await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Mid", "category_id": seed_categories[0].id, "price": 150.0},
            headers=headers,
        )
        await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Expensive", "category_id": seed_categories[0].id, "price": 500.0},
            headers=headers,
        )
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/?price_min=100&price_max=200",
            headers=headers,
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Mid"

    async def test_filter_by_service_flag(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        headers = {"Authorization": f"Bearer {token}"}
        await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "With Delivery", "category_id": seed_categories[0].id, "price": 100.0, "delivery": True},
            headers=headers,
        )
        await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "No Delivery", "category_id": seed_categories[0].id, "price": 100.0},
            headers=headers,
        )
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/?delivery=true",
            headers=headers,
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "With Delivery"

    async def test_no_filters_returns_all(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        headers = {"Authorization": f"Bearer {token}"}
        for name in ["A", "B", "C"]:
            await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": name, "category_id": seed_categories[0].id, "price": 100.0},
                headers=headers,
            )
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/",
            headers=headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 3


class TestPublicListings:
    async def test_public_listings_only_published_verified(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        create_organization: Any,
        create_user: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        # Create published listing in verified org
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Visible", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Create published listing in unverified org
        _, unverified_user_token = await create_user(email="unverified_creator@example.com")
        unverified_org_data, unverified_token = await create_organization(
            token=unverified_user_token,
            inn="5001012345",
        )
        unverified_org_id = unverified_org_data["id"]
        create_resp2 = await client.post(
            f"/api/v1/organizations/{unverified_org_id}/listings/",
            json={"name": "Invisible", "category_id": seed_categories[0].id, "price": 200.0},
            headers={"Authorization": f"Bearer {unverified_token}"},
        )
        listing_id2 = create_resp2.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{unverified_org_id}/listings/{listing_id2}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {unverified_token}"},
        )
        # Create hidden listing in verified org
        await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Hidden", "category_id": seed_categories[0].id, "price": 50.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Public list should only show "Visible"
        resp = await client.get("/api/v1/listings/")
        assert resp.status_code == 200
        body = resp.json()
        names = [item["name"] for item in body["items"]]
        assert "Visible" in names
        assert "Invisible" not in names
        assert "Hidden" not in names

    async def test_public_listings_filter_by_category(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Cat0", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        lid = create_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{lid}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {token}"},
        )
        create_resp2 = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Cat1", "category_id": seed_categories[1].id, "price": 200.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        lid2 = create_resp2.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{lid2}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await client.get(f"/api/v1/listings/?category_id={seed_categories[0].id}")
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "Cat0"

    async def test_public_listings_filter_by_org(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "OrgItem", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        lid = create_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{lid}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await client.get(f"/api/v1/listings/?organization_id={org_id}")
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["organization_id"] == org_id


class TestPublicListingsSearch:
    async def test_search_by_name(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        headers = {"Authorization": f"Bearer {token}"}
        for name in ["Excavator CAT", "Crane Liebherr", "Bulldozer"]:
            create_resp = await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": name, "category_id": seed_categories[0].id, "price": 100.0},
                headers=headers,
            )
            lid = create_resp.json()["id"]
            await client.patch(
                f"/api/v1/organizations/{org_id}/listings/{lid}/status",
                json={"status": "published"},
                headers=headers,
            )
        resp = await client.get("/api/v1/listings/?search=Excavator")
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Excavator CAT"


class TestGetListing:
    async def test_get_published_listing_from_verified_org(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Public Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Access without auth
        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Public Item"

    async def test_get_listing_unverified_org_denied_for_non_member(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Private Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        # Access without auth — org is unverified
        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.status_code == 403

    async def test_get_listing_unverified_org_allowed_for_member(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Member Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        # Access with auth as org member
        resp = await client.get(
            f"/api/v1/listings/{listing_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Member Item"

    async def test_get_listing_unverified_org_denied_for_authenticated_non_member(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Private Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        # Authenticated user who is NOT a member of the unverified org
        _, outsider_token = await create_user(email="outsider@example.com")
        resp = await client.get(
            f"/api/v1/listings/{listing_id}",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert resp.status_code == 403

    async def test_get_listing_invalid_token_treated_as_unauthenticated(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Private Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        # Invalid token — org is unverified, should be denied (treated as no auth)
        resp = await client.get(
            f"/api/v1/listings/{listing_id}",
            headers={"Authorization": "Bearer invalidtoken"},
        )
        assert resp.status_code == 403

    async def test_get_listing_not_found(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.get("/api/v1/listings/BADID1")
        assert resp.status_code == 404


class TestGetOrgListing:
    async def test_get_org_listing_as_member(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Org Item", "category_id": seed_categories[0].id, "price": 200.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == listing_id
        assert body["name"] == "Org Item"
        assert body["price"] == 200.0

    async def test_get_org_listing_any_status(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        """Members can see listings in any status (hidden, published, archived)."""
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Hidden Item", "category_id": seed_categories[0].id, "price": 50.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        # Listing defaults to hidden — should still be accessible
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "hidden"

    async def test_get_org_listing_denied_for_non_member(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Private Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        _, outsider_token = await create_user(email="outsider@example.com")
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert resp.status_code == 403

    async def test_get_org_listing_denied_without_auth(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Private Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        listing_id = create_resp.json()["id"]
        resp = await client.get(f"/api/v1/organizations/{org_id}/listings/{listing_id}")
        assert resp.status_code == 401

    async def test_get_org_listing_not_found(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/BADID1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


class TestListingOrdering:
    async def _create_and_publish(
        self,
        client: AsyncClient,
        org_id: str,
        token: str,
        category_id: str,
        name: str,
        price: float,
    ) -> str:
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": name, "category_id": category_id, "price": price},
            headers=headers,
        )
        assert create_resp.status_code == 201
        listing_id = create_resp.json()["id"]
        status_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers=headers,
        )
        assert status_resp.status_code == 200
        return listing_id

    async def test_public_listings_default_order(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        category_id = seed_categories[0].id

        id_a = await self._create_and_publish(client, org_id, token, category_id, "Alpha", 100.0)
        id_b = await self._create_and_publish(client, org_id, token, category_id, "Beta", 200.0)
        id_c = await self._create_and_publish(client, org_id, token, category_id, "Gamma", 300.0)

        resp = await client.get("/api/v1/listings/")
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        # Default order is -updated_at, so most recently updated comes first
        assert ids == [id_c, id_b, id_a]

    async def test_public_listings_order_by_price_asc(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        category_id = seed_categories[0].id

        id_a = await self._create_and_publish(client, org_id, token, category_id, "Cheap", 10.0)
        id_b = await self._create_and_publish(client, org_id, token, category_id, "Mid", 50.0)
        id_c = await self._create_and_publish(client, org_id, token, category_id, "Expensive", 99.0)

        resp = await client.get("/api/v1/listings/", params={"order_by": "price"})
        assert resp.status_code == 200
        prices = [item["price"] for item in resp.json()["items"]]
        assert prices == sorted(prices)
        ids = [item["id"] for item in resp.json()["items"]]
        assert ids == [id_a, id_b, id_c]

    async def test_public_listings_order_by_price_desc(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        category_id = seed_categories[0].id

        id_a = await self._create_and_publish(client, org_id, token, category_id, "Cheap", 10.0)
        id_b = await self._create_and_publish(client, org_id, token, category_id, "Mid", 50.0)
        id_c = await self._create_and_publish(client, org_id, token, category_id, "Expensive", 99.0)

        resp = await client.get("/api/v1/listings/", params={"order_by": "-price"})
        assert resp.status_code == 200
        prices = [item["price"] for item in resp.json()["items"]]
        assert prices == sorted(prices, reverse=True)
        ids = [item["id"] for item in resp.json()["items"]]
        assert ids == [id_c, id_b, id_a]

    async def test_public_listings_order_by_name(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        category_id = seed_categories[0].id

        await self._create_and_publish(client, org_id, token, category_id, "Zebra", 100.0)
        await self._create_and_publish(client, org_id, token, category_id, "Apple", 200.0)
        await self._create_and_publish(client, org_id, token, category_id, "Mango", 300.0)

        resp = await client.get("/api/v1/listings/", params={"order_by": "name"})
        assert resp.status_code == 200
        names = [item["name"] for item in resp.json()["items"]]
        assert names == sorted(names)

    async def test_public_listings_invalid_order_by(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        resp = await client.get("/api/v1/listings/", params={"order_by": "nonexistent"})
        assert resp.status_code == 422

    async def test_org_listings_order_by_price(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        category_id = seed_categories[0].id
        headers = {"Authorization": f"Bearer {token}"}

        id_a = await self._create_and_publish(client, org_id, token, category_id, "Cheap", 10.0)
        id_b = await self._create_and_publish(client, org_id, token, category_id, "Mid", 50.0)
        id_c = await self._create_and_publish(client, org_id, token, category_id, "Expensive", 99.0)

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/",
            params={"order_by": "price"},
            headers=headers,
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        assert ids == [id_a, id_b, id_c]

    async def test_public_listings_pagination_with_custom_order(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        category_id = seed_categories[0].id

        prices = [10.0, 30.0, 50.0, 70.0, 90.0]
        for i, price in enumerate(prices):
            await self._create_and_publish(client, org_id, token, category_id, f"Item {i}", price)

        all_ids: list[str] = []
        cursor: str | None = None

        for _ in range(3):
            params: dict[str, Any] = {"order_by": "price", "limit": 2}
            if cursor is not None:
                params["cursor"] = cursor
            resp = await client.get("/api/v1/listings/", params=params)
            assert resp.status_code == 200
            body = resp.json()
            page_ids = [item["id"] for item in body["items"]]
            assert len(page_ids) > 0
            all_ids.extend(page_ids)
            cursor = body.get("next_cursor")
            if not body["has_more"]:
                break

        # No duplicates, no gaps: all 5 items collected
        assert len(all_ids) == 5
        assert len(set(all_ids)) == 5

        # Prices should be in ascending order across all pages
        all_prices: list[float] = []
        for listing_id in all_ids:
            resp = await client.get(f"/api/v1/listings/{listing_id}")
            assert resp.status_code == 200
            all_prices.append(resp.json()["price"])
        assert all_prices == sorted(all_prices)
