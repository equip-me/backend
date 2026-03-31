from typing import Any

import pytest
from httpx import AsyncClient

from app.core.enums import UserRole
from app.users.models import User

pytestmark = pytest.mark.anyio

URL = "/api/v1/private/users/"


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
