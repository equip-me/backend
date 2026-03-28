from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient


def _today() -> date:
    return datetime.now(UTC).date()


async def _create_order(
    client: AsyncClient,
    listing_id: str,
    token: str,
    start_offset: int = 1,
    duration: int = 4,
) -> dict[str, Any]:
    start = _today() + timedelta(days=start_offset)
    end = start + timedelta(days=duration)
    resp = await client.post(
        "/orders/",
        json={
            "listing_id": listing_id,
            "requested_start_date": start.isoformat(),
            "requested_end_date": end.isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.anyio
class TestCreateOrder:
    async def test_create_order_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        start = _today() + timedelta(days=1)
        end = start + timedelta(days=4)

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert body["listing_id"] == listing_id
        assert body["estimated_cost"] is not None

    async def test_create_order_listing_not_found(
        self,
        client: AsyncClient,
        renter_token: str,
    ) -> None:
        start = _today() + timedelta(days=1)
        end = start + timedelta(days=4)

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": "XXXXXX",
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 404

    async def test_create_order_listing_not_published(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: Any,
        renter_token: str,
    ) -> None:
        org_data, org_token = verified_org
        org_id = org_data["id"]

        resp = await client.post(
            f"/organizations/{org_id}/listings/",
            json={
                "name": "Hidden item",
                "category_id": seed_categories[0].id,
                "price": 1000.00,
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 201
        listing_id = resp.json()["id"]

        start = _today() + timedelta(days=1)
        end = start + timedelta(days=2)
        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 400

    async def test_create_order_unverified_org(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: Any,
        renter_token: str,
    ) -> None:
        org_data, org_token = await create_organization()
        org_id = org_data["id"]

        resp = await client.post(
            f"/organizations/{org_id}/listings/",
            json={
                "name": "Unverified item",
                "category_id": seed_categories[0].id,
                "price": 1000.00,
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 201
        listing_id = resp.json()["id"]

        patch_resp = await client.patch(
            f"/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert patch_resp.status_code == 200, patch_resp.text

        start = _today() + timedelta(days=1)
        end = start + timedelta(days=2)
        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 403

    async def test_create_order_start_in_past(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": (_today() - timedelta(days=1)).isoformat(),
                "requested_end_date": _today().isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 400

    async def test_create_order_start_after_end(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        start = _today() + timedelta(days=5)
        end = _today() + timedelta(days=1)

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 422

    async def test_create_order_estimated_cost_calculation(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        start = _today() + timedelta(days=1)
        end = start + timedelta(days=4)

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        body = resp.json()
        assert body["estimated_cost"] == "25000.00"

    async def test_create_order_unauthenticated(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        start = _today() + timedelta(days=1)
        end = start + timedelta(days=2)

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
        )
        assert resp.status_code == 401


async def _create_offered_order(
    client: AsyncClient,
    listing_id: str,
    org_id: str,
    org_token: str,
    renter_token: str,
) -> dict[str, Any]:
    order = await _create_order(client, listing_id, renter_token)
    start = _today() + timedelta(days=2)
    end = start + timedelta(days=5)
    resp = await client.patch(
        f"/organizations/{org_id}/orders/{order['id']}/offer",
        json={
            "offered_cost": "30000.00",
            "offered_start_date": start.isoformat(),
            "offered_end_date": end.isoformat(),
        },
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.anyio
class TestOfferOrder:
    async def test_offer_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        start = _today() + timedelta(days=2)
        end = start + timedelta(days=5)
        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "offered"
        assert body["offered_cost"] == "30000.00"

    async def test_re_offer_updates_terms(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        start = _today() + timedelta(days=2)
        end = start + timedelta(days=5)
        await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )

        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "25000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["offered_cost"] == "25000.00"
        assert resp.json()["status"] == "offered"

    async def test_offer_wrong_org(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        create_organization: Any,
        create_user: Any,
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        # create_organization() defaults to "orgcreator@example.com" which is already taken
        # by the verified_org fixture. Use a separate user + distinct INN to avoid 409.
        _, other_token = await create_user(email="other_org_owner@example.com")
        other_org_data, other_token = await create_organization(token=other_token, inn="7707083894")
        other_org_id = other_org_data["id"]

        start = _today() + timedelta(days=2)
        end = start + timedelta(days=5)
        resp = await client.patch(
            f"/organizations/{other_org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404

    async def test_offer_invalid_status(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        start = _today() + timedelta(days=2)
        end = start + timedelta(days=5)
        offer_data = {
            "offered_cost": "30000.00",
            "offered_start_date": start.isoformat(),
            "offered_end_date": end.isoformat(),
        }

        await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json=offer_data,
            headers={"Authorization": f"Bearer {org_token}"},
        )
        await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json=offer_data,
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 400


@pytest.mark.anyio
class TestRejectOrder:
    async def test_reject_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/reject",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    async def test_reject_non_pending(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        start = _today() + timedelta(days=2)
        end = start + timedelta(days=5)
        await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )

        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/reject",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 400


@pytest.mark.anyio
class TestConfirmOrder:
    async def test_confirm_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        resp = await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

    async def test_confirm_not_requester(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        create_user: Any,
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        _, other_token = await create_user(
            email="other@example.com",
            phone="+79009998877",
            name="Other",
            surname="User",
        )
        resp = await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    async def test_confirm_non_offered(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 400


@pytest.mark.anyio
class TestDeclineOrder:
    async def test_decline_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        resp = await client.patch(
            f"/orders/{order['id']}/decline",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "declined"


@pytest.mark.anyio
class TestCancelOrder:
    async def test_user_cancel_confirmed(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.patch(
            f"/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

    async def test_org_cancel_confirmed(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"

    async def test_cancel_pending_fails(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 400


@pytest.mark.anyio
class TestListOrders:
    async def test_list_user_orders(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing_id, renter_token, start_offset=10)

        resp = await client.get(
            "/orders/",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_user_orders_empty(
        self,
        client: AsyncClient,
        renter_token: str,
    ) -> None:
        resp = await client.get(
            "/orders/",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_org_orders(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        await _create_order(client, listing_id, renter_token)

        resp = await client.get(
            f"/organizations/{org_id}/orders/",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_list_org_orders_unauthorized(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        _listing_id, org_id, _org_token = create_listing

        resp = await client.get(
            f"/organizations/{org_id}/orders/",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 403


@pytest.mark.anyio
class TestGetOrder:
    async def test_get_user_order(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.get(
            f"/orders/{order['id']}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == order["id"]

    async def test_get_org_order(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.get(
            f"/organizations/{org_id}/orders/{order['id']}",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == order["id"]

    async def test_get_order_not_requester(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        create_user: Any,
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        _, other_token = await create_user(
            email="stranger@example.com",
            phone="+79005554433",
            name="Stranger",
            surname="Person",
        )
        resp = await client.get(
            f"/orders/{order['id']}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403


@pytest.mark.anyio
class TestListingSideEffects:
    async def test_cancel_active_restores_listing_to_published(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing

        start = _today()
        end = start + timedelta(days=5)
        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 201
        order_id = resp.json()["id"]

        await client.patch(
            f"/organizations/{org_id}/orders/{order_id}/offer",
            json={
                "offered_cost": "25000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )

        await client.patch(
            f"/orders/{order_id}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        # Fetch the order — lazy eval should transition to active since start is today
        resp = await client.get(
            f"/orders/{order_id}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.json()["status"] == "active"

        # Check listing is in_rent
        resp = await client.get(f"/listings/{listing_id}")
        assert resp.json()["status"] == "in_rent"

        # Cancel the order
        resp = await client.patch(
            f"/orders/{order_id}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

        # Check listing is published again
        resp = await client.get(f"/listings/{listing_id}")
        assert resp.json()["status"] == "published"

    async def test_cancel_confirmed_does_not_change_listing(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.get(f"/listings/{listing_id}")
        assert resp.json()["status"] == "published"

        await client.patch(
            f"/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.get(f"/listings/{listing_id}")
        assert resp.json()["status"] == "published"
