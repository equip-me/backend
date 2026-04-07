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
