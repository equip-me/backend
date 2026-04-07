"""E2E test: search users by email and invite to organization."""

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.enums import MembershipRole, MembershipStatus, OrganizationStatus
from app.organizations.models import Membership, Organization

pytestmark = pytest.mark.e2e


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_search_and_invite_flow(client: httpx.AsyncClient, create_user: Any) -> None:
    """Org admin searches for a user by email, then invites them using the returned user_id."""
    # Create org admin and their organization
    _, admin_token = await create_user(email="orgadmin@example.com")

    dadata_result = [
        {
            "value": "ООО Тест",
            "data": {
                "name": {"short_with_opf": "ООО Тест", "full_with_opf": "ООО Тестовая Компания"},
                "inn": "7707083893",
                "kpp": "770701001",
                "ogrn": "1027700132195",
                "address": {"unrestricted_value": "г Москва"},
            },
        },
    ]
    with patch("app.organizations.dependencies.get_dadata_client") as mock_dadata:
        mock_client = AsyncMock()
        mock_client.suggest.return_value = dadata_result
        mock_dadata.return_value = mock_client
        org_resp = await client.post(
            "/api/v1/organizations/",
            json={
                "inn": "7707083893",
                "contacts": [{"display_name": "Admin", "phone": "+79991234567"}],
            },
            headers=_auth(admin_token),
        )
    assert org_resp.status_code == 200
    org_id = org_resp.json()["id"]
    await Organization.filter(id=org_id).update(status=OrganizationStatus.VERIFIED)

    # Create a target user to find
    target_data, _ = await create_user(email="target.user@company.com", phone="+79001112233")

    # Search for the target user by email
    search_resp = await client.get(
        "/api/v1/users/search",
        params={"email": "target.user"},
        headers=_auth(admin_token),
    )
    assert search_resp.status_code == 200
    results = search_resp.json()
    assert len(results) == 1
    found_user = results[0]
    assert found_user["id"] == target_data["id"]
    assert found_user["email"] == "target.user@company.com"
    assert found_user["name"] == target_data["name"]
    assert "profile_photo" in found_user

    # Use the found user_id to invite them
    invite_resp = await client.post(
        f"/api/v1/organizations/{org_id}/members/invite",
        json={"user_id": found_user["id"], "role": MembershipRole.EDITOR},
        headers=_auth(admin_token),
    )
    assert invite_resp.status_code == 200
    membership = invite_resp.json()
    assert membership["status"] == MembershipStatus.INVITED
    assert membership["role"] == MembershipRole.EDITOR

    # Verify membership was created in DB
    db_membership = await Membership.get(user_id=target_data["id"], organization_id=org_id)
    assert db_membership.status == MembershipStatus.INVITED
