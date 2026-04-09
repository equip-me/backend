from typing import Any

import pytest
from httpx import AsyncClient

from app.core.enums import OrganizationStatus, UserRole
from app.listings.models import ListingCategory
from app.organizations.models import Organization
from app.users.models import User

pytestmark = pytest.mark.anyio

URL = "/api/v1/private/users/"
ORG_URL = "/api/v1/private/organizations/"


class TestListUsers:
    async def test_admin_success(
        self, client: AsyncClient, admin_user: tuple[dict[str, Any], str], create_user: Any
    ) -> None:
        _, admin_token = admin_user
        await create_user(email="user1@example.com", name="Alice", surname="Smith")
        await create_user(email="user2@example.com", name="Bob", surname="Jones")

        resp = await client.get(URL, headers={"Authorization": f"Bearer {admin_token}"})

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "has_more" in body
        assert "next_cursor" in body
        # admin + 2 users = 3
        assert len(body["items"]) == 3

    async def test_requires_admin(self, client: AsyncClient, create_user: Any) -> None:
        _, regular_token = await create_user(email="regular@example.com")

        resp = await client.get(URL, headers={"Authorization": f"Bearer {regular_token}"})

        assert resp.status_code == 403

    async def test_search(self, client: AsyncClient, admin_user: tuple[dict[str, Any], str], create_user: Any) -> None:
        _, admin_token = admin_user
        await create_user(email="alice@example.com", name="Alice", surname="Wonder")
        await create_user(email="bob@example.com", name="Bob", surname="Builder")

        resp = await client.get(URL, params={"search": "Alice"}, headers={"Authorization": f"Bearer {admin_token}"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "Alice"

    async def test_search_by_email(
        self, client: AsyncClient, admin_user: tuple[dict[str, Any], str], create_user: Any
    ) -> None:
        _, admin_token = admin_user
        await create_user(email="unique-search@example.com", name="Charlie", surname="Day")

        resp = await client.get(
            URL, params={"search": "unique-search"}, headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "Charlie"

    async def test_role_filter(
        self, client: AsyncClient, admin_user: tuple[dict[str, Any], str], create_user: Any
    ) -> None:
        _, admin_token = admin_user
        user_data, _ = await create_user(email="suspended@example.com", name="Suspended", surname="User")
        await User.filter(id=user_data["id"]).update(role=UserRole.SUSPENDED)

        resp = await client.get(URL, params={"role": "suspended"}, headers={"Authorization": f"Bearer {admin_token}"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["role"] == "suspended"

    async def test_pagination(
        self, client: AsyncClient, admin_user: tuple[dict[str, Any], str], create_user: Any
    ) -> None:
        _, admin_token = admin_user
        for i in range(4):
            await create_user(email=f"page{i}@example.com", name=f"User{i}", surname="Test")

        # 5 total users (admin + 4 created), limit=3
        resp = await client.get(URL, params={"limit": 3}, headers={"Authorization": f"Bearer {admin_token}"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 3
        assert body["has_more"] is True
        assert body["next_cursor"] is not None

        # Fetch second page
        resp2 = await client.get(
            URL, params={"limit": 3, "cursor": body["next_cursor"]}, headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert resp2.status_code == 200
        body2 = resp2.json()
        assert len(body2["items"]) == 2
        assert body2["has_more"] is False

        # No overlap between pages
        page1_ids = {item["id"] for item in body["items"]}
        page2_ids = {item["id"] for item in body2["items"]}
        assert page1_ids.isdisjoint(page2_ids)


class TestListAllOrganizations:
    async def test_admin_lists_all_orgs(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_organization: Any,
    ) -> None:
        _, admin_token = admin_user
        org_data, org_token = await create_organization()
        org_id = org_data["id"]
        # One stays CREATED, make another VERIFIED
        await create_organization(token=org_token, inn="7736207543")
        await Organization.filter(id=org_id).update(status=OrganizationStatus.VERIFIED)

        resp = await client.get(ORG_URL, headers={"Authorization": f"Bearer {admin_token}"})

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "has_more" in body
        assert "next_cursor" in body
        assert len(body["items"]) == 2
        statuses = {item["status"] for item in body["items"]}
        assert statuses == {"created", "verified"}

    async def test_requires_admin(self, client: AsyncClient, create_user: Any) -> None:
        _, regular_token = await create_user(email="regular@example.com")

        resp = await client.get(ORG_URL, headers={"Authorization": f"Bearer {regular_token}"})

        assert resp.status_code == 403

    async def test_status_filter(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_organization: Any,
    ) -> None:
        _, admin_token = admin_user
        org_data, org_token = await create_organization()
        org_id = org_data["id"]
        await Organization.filter(id=org_id).update(status=OrganizationStatus.VERIFIED)
        await create_organization(token=org_token, inn="7736207543")  # stays CREATED

        resp_created = await client.get(
            ORG_URL, params={"status": "created"}, headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp_created.status_code == 200
        assert all(item["status"] == "created" for item in resp_created.json()["items"])

        resp_verified = await client.get(
            ORG_URL, params={"status": "verified"}, headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp_verified.status_code == 200
        assert all(item["status"] == "verified" for item in resp_verified.json()["items"])

    async def test_search(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_organization: Any,
    ) -> None:
        _, admin_token = admin_user
        await create_organization()

        resp = await client.get(ORG_URL, params={"search": "Рога"}, headers={"Authorization": f"Bearer {admin_token}"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1

    async def test_pagination(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_organization: Any,
    ) -> None:
        _, admin_token = admin_user
        inns = ["7707083893", "7736207543", "5024129032", "7710140679"]
        _, org_token = await create_organization(inn=inns[0])
        for inn in inns[1:]:
            await create_organization(token=org_token, inn=inn)

        resp = await client.get(ORG_URL, params={"limit": 2}, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["has_more"] is True

        resp2 = await client.get(
            ORG_URL,
            params={"limit": 2, "cursor": body["next_cursor"]},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert len(body2["items"]) == 2
        assert body2["has_more"] is False

        page1_ids = {item["id"] for item in body["items"]}
        page2_ids = {item["id"] for item in body2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    async def test_published_listing_count(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_organization: Any,
        seed_categories: list[ListingCategory],
    ) -> None:
        _, admin_token = admin_user
        org_data, org_token = await create_organization()
        org_id = org_data["id"]
        await Organization.filter(id=org_id).update(status=OrganizationStatus.VERIFIED)
        headers = {"Authorization": f"Bearer {org_token}"}

        # Create 2 listings, publish only 1
        for i in range(2):
            create_resp = await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": f"Item {i}", "category_id": seed_categories[0].id, "price": 100.0},
                headers=headers,
            )
            assert create_resp.status_code == 201
            if i == 0:
                listing_id = create_resp.json()["id"]
                await client.patch(
                    f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
                    json={"status": "published"},
                    headers=headers,
                )

        resp = await client.get(ORG_URL, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        org_item = next(item for item in items if item["id"] == org_id)
        assert org_item["published_listing_count"] == 1


class TestAdminUserOrdering:
    async def test_admin_users_order_by_email(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_user: Any,
    ) -> None:
        _, admin_token = admin_user
        await create_user(email="alice@example.com", phone="+79990000001")
        await create_user(email="bob@example.com", phone="+79990000002")
        await create_user(email="charlie@example.com", phone="+79990000003")
        resp = await client.get(
            "/api/v1/private/users/",
            params={"order_by": "email"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        emails = [item["email"] for item in items]
        assert emails == sorted(emails)

    async def test_admin_users_order_by_surname_desc(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_user: Any,
    ) -> None:
        _, admin_token = admin_user
        await create_user(email="a@example.com", phone="+79990000001", surname="Яковлев")
        await create_user(email="b@example.com", phone="+79990000002", surname="Абрамов")
        resp = await client.get(
            "/api/v1/private/users/",
            params={"order_by": "-surname"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        surnames = [item["surname"] for item in items]
        assert surnames == sorted(surnames, reverse=True)

    async def test_admin_users_invalid_order_by(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        _, admin_token = admin_user
        resp = await client.get(
            "/api/v1/private/users/",
            params={"order_by": "invalid"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422


class TestAdminOrganizationOrdering:
    async def test_admin_orgs_order_by_short_name(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_organization: Any,
        create_user: Any,
    ) -> None:
        _, admin_token = admin_user
        await create_organization(token=None, inn="7707083893")
        _, token2 = await create_user(email="orgcreator2@example.com")
        await create_organization(token=token2, inn="7736207543")
        resp = await client.get(
            "/api/v1/private/organizations/",
            params={"order_by": "short_name"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        names = [item["short_name"] for item in items]
        assert names == sorted(names)

    async def test_admin_orgs_invalid_order_by(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        _, admin_token = admin_user
        resp = await client.get(
            "/api/v1/private/organizations/",
            params={"order_by": "invalid"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422
