from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from tests.conftest import _default_org_data


class TestCreateOrganization:
    async def test_create_org_success(
        self,
        client: AsyncClient,
        create_user: Any,
        mock_dadata: MagicMock,
    ) -> None:
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post(
            "/organizations/",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["inn"] == "7707083893"
        assert body["short_name"] == 'ООО "Рога и копыта"'
        assert body["status"] == "created"
        assert len(body["contacts"]) == 1
        assert body["contacts"][0]["display_name"] == "Иван Иванов"
        mock_dadata.find_by_id.assert_called_once_with("party", "7707083893")

    @pytest.mark.skip(reason="needs list members endpoint")
    async def test_create_org_creator_becomes_admin(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post(
            "/organizations/",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        org_id = resp.json()["id"]
        members_resp = await client.get(
            f"/organizations/{org_id}/members",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert members_resp.status_code == 200
        members = members_resp.json()
        assert len(members) == 1
        assert members[0]["role"] == "admin"
        assert members[0]["status"] == "member"

    async def test_create_org_duplicate_inn(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token1 = await create_user()
        _, token2 = await create_user(email="other@example.com")
        data = _default_org_data()
        await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token1}"})
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token2}"})
        assert resp.status_code == 409

    async def test_create_org_invalid_inn(self, client: AsyncClient, create_user: Any) -> None:
        _, token = await create_user()
        data = _default_org_data(inn="123")
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    async def test_create_org_no_contacts(self, client: AsyncClient, create_user: Any) -> None:
        _, token = await create_user()
        data = _default_org_data(contacts=[])
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    async def test_create_org_contact_missing_phone_and_email(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token = await create_user()
        data = _default_org_data(contacts=[{"display_name": "Test"}])
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    async def test_create_org_dadata_failure(
        self,
        client: AsyncClient,
        create_user: Any,
        mock_dadata: MagicMock,
    ) -> None:
        mock_dadata.find_by_id.side_effect = Exception("Dadata unavailable")
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 502

    async def test_create_org_dadata_empty(
        self,
        client: AsyncClient,
        create_user: Any,
        mock_dadata: MagicMock,
    ) -> None:
        mock_dadata.find_by_id.return_value = []
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 502

    async def test_create_org_unauthenticated(self, client: AsyncClient) -> None:
        data = _default_org_data()
        resp = await client.post("/organizations/", json=data)
        assert resp.status_code == 401
