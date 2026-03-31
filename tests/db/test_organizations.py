from typing import Any
from unittest.mock import MagicMock

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
            "/api/v1/organizations/",
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

    async def test_create_org_creator_becomes_admin(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post(
            "/api/v1/organizations/",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        org_id = resp.json()["id"]
        members_resp = await client.get(
            f"/api/v1/organizations/{org_id}/members",
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
        await client.post("/api/v1/organizations/", json=data, headers={"Authorization": f"Bearer {token1}"})
        resp = await client.post("/api/v1/organizations/", json=data, headers={"Authorization": f"Bearer {token2}"})
        assert resp.status_code == 409

    async def test_create_org_invalid_inn(self, client: AsyncClient, create_user: Any) -> None:
        _, token = await create_user()
        data = _default_org_data(inn="123")
        resp = await client.post("/api/v1/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    async def test_create_org_no_contacts(self, client: AsyncClient, create_user: Any) -> None:
        _, token = await create_user()
        data = _default_org_data(contacts=[])
        resp = await client.post("/api/v1/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    async def test_create_org_contact_missing_phone_and_email(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token = await create_user()
        data = _default_org_data(contacts=[{"display_name": "Test"}])
        resp = await client.post("/api/v1/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
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
        resp = await client.post("/api/v1/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
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
        resp = await client.post("/api/v1/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 502

    async def test_create_org_unauthenticated(self, client: AsyncClient) -> None:
        data = _default_org_data()
        resp = await client.post("/api/v1/organizations/", json=data)
        assert resp.status_code == 401


class TestGetOrganization:
    async def test_get_org_by_id(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, _ = await create_organization()
        resp = await client.get(f"/api/v1/organizations/{org_data['id']}")
        assert resp.status_code == 200
        assert resp.json()["inn"] == "7707083893"
        assert len(resp.json()["contacts"]) == 1

    async def test_get_org_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/organizations/ZZZZZZ")
        assert resp.status_code == 404


class TestListUserOrganizations:
    async def test_list_my_orgs(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, token = await create_organization()
        resp = await client.get("/api/v1/users/me/organizations", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        orgs = resp.json()
        assert len(orgs) == 1
        assert orgs[0]["id"] == org_data["id"]

    async def test_list_my_orgs_empty(self, client: AsyncClient, create_user: Any) -> None:
        _, token = await create_user()
        resp = await client.get("/api/v1/users/me/organizations", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_my_orgs_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/users/me/organizations")
        assert resp.status_code == 401


class TestReplaceContacts:
    async def test_replace_contacts(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, token = await create_organization()
        new_contacts = {
            "contacts": [
                {"display_name": "Новый контакт", "phone": "+79998887766"},
                {"display_name": "Отдел аренды", "email": "rent@example.com"},
            ],
        }
        resp = await client.put(
            f"/api/v1/organizations/{org_data['id']}/contacts",
            json=new_contacts,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        contacts = resp.json()
        assert len(contacts) == 2
        assert contacts[0]["display_name"] == "Новый контакт"
        assert contacts[1]["display_name"] == "Отдел аренды"

    async def test_replace_contacts_empty_list(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, token = await create_organization()
        resp = await client.put(
            f"/api/v1/organizations/{org_data['id']}/contacts",
            json={"contacts": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    async def test_replace_contacts_not_admin(
        self, client: AsyncClient, create_organization: Any, create_user: Any
    ) -> None:
        org_data, _ = await create_organization()
        _, other_token = await create_user(email="other@example.com")
        resp = await client.put(
            f"/api/v1/organizations/{org_data['id']}/contacts",
            json={"contacts": [{"display_name": "Test", "phone": "+79991112233"}]},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    async def test_replace_contacts_org_not_found(self, client: AsyncClient, create_user: Any) -> None:
        _, token = await create_user()
        resp = await client.put(
            "/api/v1/organizations/ZZZZZZ/contacts",
            json={"contacts": [{"display_name": "Test", "phone": "+79991112233"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


_PAYMENT_DATA = {
    "payment_account": "40702810000000000001",
    "bank_bic": "044525225",
    "bank_inn": "7707083893",
    "bank_name": "ПАО Сбербанк",
    "bank_correspondent_account": "30101810400000000225",
}


class TestPaymentDetails:
    async def test_create_payment_details(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, token = await create_organization()
        resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/payment-details",
            json=_PAYMENT_DATA,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["payment_account"] == "40702810000000000001"
        assert body["bank_name"] == "ПАО Сбербанк"
        assert "id" in body

    async def test_upsert_payment_details(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, token = await create_organization()
        await client.post(
            f"/api/v1/organizations/{org_data['id']}/payment-details",
            json=_PAYMENT_DATA,
            headers={"Authorization": f"Bearer {token}"},
        )
        updated = {**_PAYMENT_DATA, "bank_name": "АО Тинькофф Банк"}
        resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/payment-details",
            json=updated,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["bank_name"] == "АО Тинькофф Банк"

    async def test_get_payment_details(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, token = await create_organization()
        await client.post(
            f"/api/v1/organizations/{org_data['id']}/payment-details",
            json=_PAYMENT_DATA,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await client.get(
            f"/api/v1/organizations/{org_data['id']}/payment-details",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["bank_name"] == "ПАО Сбербанк"

    async def test_get_payment_details_not_set(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, token = await create_organization()
        resp = await client.get(
            f"/api/v1/organizations/{org_data['id']}/payment-details",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    async def test_create_payment_details_not_admin(
        self, client: AsyncClient, create_organization: Any, create_user: Any
    ) -> None:
        org_data, _ = await create_organization()
        _, other_token = await create_user(email="other@example.com")
        resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/payment-details",
            json=_PAYMENT_DATA,
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403


class TestMembershipInvite:
    async def test_invite_user(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        user_data, _ = await create_user(email="invitee@example.com")
        resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == user_data["id"]
        assert body["role"] == "editor"
        assert body["status"] == "invited"

    async def test_invite_nonexistent_user(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, admin_token = await create_organization()
        resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": "ZZZZZZ", "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_invite_duplicate(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        user_data, _ = await create_user(email="invitee@example.com")
        await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    async def test_invite_not_admin(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, _ = await create_organization()
        _, other_token = await create_user(email="nonadmin@example.com")
        user_data, _ = await create_user(email="invitee@example.com")
        resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403


class TestMembershipJoin:
    async def test_join_request(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, _ = await create_organization()
        _, user_token = await create_user(email="joiner@example.com")
        resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "viewer"
        assert body["status"] == "candidate"

    async def test_join_duplicate(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, _ = await create_organization()
        _, user_token = await create_user(email="joiner@example.com")
        join_url = f"/api/v1/organizations/{org_data['id']}/members/join"
        auth = {"Authorization": f"Bearer {user_token}"}
        await client.post(join_url, headers=auth)
        resp = await client.post(join_url, headers=auth)
        assert resp.status_code == 409

    async def test_join_already_member(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, admin_token = await create_organization()
        join_url = f"/api/v1/organizations/{org_data['id']}/members/join"
        resp = await client.post(join_url, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 409


class TestMembershipApprove:
    async def test_approve_not_found(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, admin_token = await create_organization()
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{fake_id}/approve",
            json={"role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_approve_candidate(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        _, user_token = await create_user(email="joiner@example.com")
        join_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        member_id = join_resp.json()["id"]
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/approve",
            json={"role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "editor"
        assert resp.json()["status"] == "member"

    async def test_approve_wrong_status(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        user_data, _ = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        # Try to approve an INVITED membership (should fail — approve is for CANDIDATE only)
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/approve",
            json={"role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    async def test_approve_not_admin(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, _ = await create_organization()
        _, user_token = await create_user(email="joiner@example.com")
        join_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        member_id = join_resp.json()["id"]
        # Non-admin tries to approve
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/approve",
            json={"role": "editor"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403


class TestMembershipAccept:
    async def test_accept_not_found(self, client: AsyncClient, create_user: Any, create_organization: Any) -> None:
        org_data, _ = await create_organization()
        _, user_token = await create_user(email="someone@example.com")
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{fake_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 404

    async def test_accept_invitation(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "member"
        assert resp.json()["role"] == "editor"

    async def test_accept_wrong_user(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        user_data, _ = await create_user(email="invitee@example.com")
        _, other_token = await create_user(email="other@example.com")
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    async def test_accept_wrong_status(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, _ = await create_organization()
        _, user_token = await create_user(email="joiner@example.com")
        join_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        member_id = join_resp.json()["id"]
        # Try to accept a CANDIDATE membership (should fail — accept is for INVITED only)
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 400


class TestMembershipRoleChange:
    async def test_change_role_not_found(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, admin_token = await create_organization()
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{fake_id}/role",
            json={"role": "viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_change_role(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/role",
            json={"role": "viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "viewer"

    async def test_change_role_not_member_status(
        self, client: AsyncClient, create_organization: Any, create_user: Any
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, _ = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        # Try to change role of an INVITED membership (not yet a member)
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/role",
            json={"role": "viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    async def test_demote_admin_with_two_admins(
        self, client: AsyncClient, create_organization: Any, create_user: Any
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="second_admin@example.com")
        # Invite as editor, accept, then promote to admin
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "admin"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        # Now demote the original admin — should succeed since there are 2 admins
        members_resp = await client.get(
            f"/api/v1/organizations/{org_data['id']}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        original_admin = next(m for m in members_resp.json() if m["id"] != member_id)
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{original_admin['id']}/role",
            json={"role": "editor"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "editor"

    async def test_demote_last_admin(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, admin_token = await create_organization()
        members_resp = await client.get(
            f"/api/v1/organizations/{org_data['id']}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        admin_member_id = members_resp.json()[0]["id"]
        resp = await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{admin_member_id}/role",
            json={"role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400


class TestMembershipRemove:
    async def test_remove_not_found(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, admin_token = await create_organization()
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.delete(
            f"/api/v1/organizations/{org_data['id']}/members/{fake_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_admin_removes_member(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.delete(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 204

    async def test_self_removal(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.delete(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 204

    async def test_last_admin_cannot_leave(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, admin_token = await create_organization()
        members_resp = await client.get(
            f"/api/v1/organizations/{org_data['id']}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        admin_member_id = members_resp.json()[0]["id"]
        resp = await client.delete(
            f"/api/v1/organizations/{org_data['id']}/members/{admin_member_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    async def test_non_admin_cannot_remove_others(
        self, client: AsyncClient, create_organization: Any, create_user: Any
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="editor@example.com")
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        # Get admin's member ID
        members_resp = await client.get(
            f"/api/v1/organizations/{org_data['id']}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        admin_member = next(m for m in members_resp.json() if m["role"] == "admin")
        # Editor tries to remove admin
        resp = await client.delete(
            f"/api/v1/organizations/{org_data['id']}/members/{admin_member['id']}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403


class TestMembershipList:
    async def test_list_members(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.get(
            f"/api/v1/organizations/{org_data['id']}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_members_non_member(
        self, client: AsyncClient, create_organization: Any, create_user: Any
    ) -> None:
        org_data, _ = await create_organization()
        _, other_token = await create_user(email="outsider@example.com")
        resp = await client.get(
            f"/api/v1/organizations/{org_data['id']}/members",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403


class TestRequireOrgEditor:
    """Test editor permission via POST /organizations/{org_id}/listings/categories/ (requires editor role)."""

    async def test_editor_passes(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        org_id = org_data["id"]
        user_data, user_token = await create_user(email="editor@example.com")
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_id}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_id}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/categories/",
            json={"name": "Editor Category"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201

    async def test_admin_passes(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, admin_token = await create_organization()
        org_id = org_data["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/categories/",
            json={"name": "Admin Category"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201

    async def test_viewer_rejected(self, client: AsyncClient, create_organization: Any, create_user: Any) -> None:
        org_data, admin_token = await create_organization()
        org_id = org_data["id"]
        user_data, user_token = await create_user(email="viewer@example.com")
        invite_resp = await client.post(
            f"/api/v1/organizations/{org_id}/members/invite",
            json={"user_id": user_data["id"], "role": "viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_id}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/categories/",
            json={"name": "Viewer Category"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403


class TestVerifyOrganization:
    async def test_verify_org(
        self,
        client: AsyncClient,
        create_organization: Any,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        org_data, _ = await create_organization()
        _, admin_token = admin_user
        resp = await client.patch(
            f"/api/v1/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "verified"

    async def test_verify_org_idempotent(
        self,
        client: AsyncClient,
        create_organization: Any,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        org_data, _ = await create_organization()
        _, admin_token = admin_user
        await client.patch(
            f"/api/v1/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = await client.patch(
            f"/api/v1/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "verified"

    async def test_verify_org_not_admin(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, token = await create_organization()
        resp = await client.patch(
            f"/api/v1/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_verify_org_not_found(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        _, admin_token = admin_user
        resp = await client.patch(
            "/api/v1/private/organizations/ZZZZZZ/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404
