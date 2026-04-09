from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

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
        "/api/v1/orders/",
        json={
            "listing_id": listing_id,
            "requested_start_date": start.isoformat(),
            "requested_end_date": end.isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return cast("dict[str, Any]", resp.json())


async def _create_second_listing(
    client: AsyncClient,
    org_id: str,
    org_token: str,
    seed_categories: list[Any],
) -> str:
    """Create a second published listing in the same org. Returns listing_id."""
    resp = await client.post(
        f"/api/v1/organizations/{org_id}/listings/",
        json={
            "name": "Crane Liebherr LTM",
            "category_id": seed_categories[0].id,
            "price": 8000.00,
        },
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert resp.status_code == 201
    listing_id = cast("str", resp.json()["id"])
    patch_resp = await client.patch(
        f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
        json={"status": "published"},
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert patch_resp.status_code == 200
    return listing_id


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
            "/api/v1/orders/",
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
            "/api/v1/orders/",
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
            f"/api/v1/organizations/{org_id}/listings/",
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
            "/api/v1/orders/",
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
            f"/api/v1/organizations/{org_id}/listings/",
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
            f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert patch_resp.status_code == 200, patch_resp.text

        start = _today() + timedelta(days=1)
        end = start + timedelta(days=2)
        resp = await client.post(
            "/api/v1/orders/",
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
            "/api/v1/orders/",
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
            "/api/v1/orders/",
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
            "/api/v1/orders/",
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
            "/api/v1/orders/",
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
        f"/api/v1/organizations/{org_id}/orders/{order['id']}/offer",
        json={
            "offered_cost": "30000.00",
            "offered_start_date": start.isoformat(),
            "offered_end_date": end.isoformat(),
        },
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert resp.status_code == 200
    return cast("dict[str, Any]", resp.json())


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
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/offer",
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
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/offer",
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
            f"/api/v1/organizations/{other_org_id}/orders/{order['id']}/offer",
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

        # Advance to CONFIRMED via offer -> accept -> approve
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/offer",
            json=offer_data,
            headers={"Authorization": f"Bearer {org_token}"},
        )
        await client.patch(
            f"/api/v1/orders/{order['id']}/accept",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/approve",
            headers={"Authorization": f"Bearer {org_token}"},
        )

        # Re-offering from CONFIRMED should be rejected
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/offer",
            json=offer_data,
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 400

    async def test_offer_negative_cost_rejected(
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
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "-100.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 422

    async def test_offer_end_before_start_rejected(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        start = _today() + timedelta(days=5)
        end = _today() + timedelta(days=2)
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 422


@pytest.mark.anyio
class TestOrderNotFound:
    async def test_get_nonexistent_order_returns_404(
        self,
        client: AsyncClient,
        renter_token: str,
    ) -> None:
        # get_order_or_404 raises NotFoundError (404) before the requester check runs
        resp = await client.get(
            "/api/v1/orders/XXXXXX",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 404

    async def test_get_org_order_not_found(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        _listing_id, org_id, org_token = create_listing
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/XXXXXX",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 404


@pytest.mark.anyio
class TestOrgCancelFromPending:
    async def test_org_cancel_pending_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"

    async def test_org_cancel_finished_fails(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Cancel from a terminal status should fail."""
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        # Cancel first (terminal)
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {org_token}"},
        )

        # Try to cancel again from terminal status
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 400


@pytest.mark.anyio
class TestAcceptOrder:
    async def test_accept_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        resp = await client.patch(
            f"/api/v1/orders/{order['id']}/accept",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    async def test_accept_not_requester(
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
            f"/api/v1/orders/{order['id']}/accept",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    async def test_accept_non_offered(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/api/v1/orders/{order['id']}/accept",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 400


@pytest.mark.anyio
class TestApproveOrder:
    async def test_approve_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        await client.patch(
            f"/api/v1/orders/{order['id']}/accept",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/approve",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

    async def test_approve_non_accepted(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Approve from offered (not accepted) should fail."""
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/approve",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 400


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
            f"/api/v1/orders/{order['id']}/accept",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/approve",
            headers={"Authorization": f"Bearer {org_token}"},
        )

        resp = await client.patch(
            f"/api/v1/orders/{order['id']}/cancel",
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
            f"/api/v1/orders/{order['id']}/accept",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/approve",
            headers={"Authorization": f"Bearer {org_token}"},
        )

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"

    async def test_cancel_pending_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Canceling from pending is allowed in the new lifecycle."""
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/api/v1/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

    async def test_cancel_terminal_fails(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Canceling from a terminal status (already canceled) should fail."""
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        await client.patch(
            f"/api/v1/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.patch(
            f"/api/v1/orders/{order['id']}/cancel",
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
            "/api/v1/orders/",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2

    async def test_list_user_orders_empty(
        self,
        client: AsyncClient,
        renter_token: str,
    ) -> None:
        resp = await client.get(
            "/api/v1/orders/",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_list_org_orders(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        await _create_order(client, listing_id, renter_token)

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    async def test_list_org_orders_unauthorized(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        _listing_id, org_id, _org_token = create_listing

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 403

    async def test_list_user_orders_filter_by_status(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        await _create_order(client, listing_id, renter_token)
        order2 = await _create_order(client, listing_id, renter_token, start_offset=10)

        # Offer the second order so it changes to "offered" status
        start = _today() + timedelta(days=2)
        end = start + timedelta(days=5)
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order2['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )

        resp = await client.get(
            "/api/v1/orders/?status=pending",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(o["status"] == "pending" for o in items)
        assert len(items) == 1


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
            f"/api/v1/orders/{order['id']}",
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
            f"/api/v1/organizations/{org_id}/orders/{order['id']}",
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
            f"/api/v1/orders/{order['id']}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403


@pytest.mark.anyio
class TestListingSideEffects:
    async def test_listing_stays_published_after_cancel_confirmed(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Listing stays published when confirmed order is canceled (reservation deleted)."""
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        await client.patch(
            f"/api/v1/orders/{order['id']}/accept",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/approve",
            headers={"Authorization": f"Bearer {org_token}"},
        )

        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.json()["status"] == "published"

        await client.patch(
            f"/api/v1/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.json()["status"] == "published"

    async def test_listing_stays_published_after_cancel_offered(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Listing stays published when offered order is canceled (no reservation)."""
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.json()["status"] == "published"

        await client.patch(
            f"/api/v1/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.json()["status"] == "published"

    async def test_listing_stays_published_throughout_lifecycle(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Listing status remains published at all order lifecycle stages."""
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        # After offer
        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.json()["status"] == "published"

        # After accept
        await client.patch(
            f"/api/v1/orders/{order['id']}/accept",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.json()["status"] == "published"

        # After approve (confirmed)
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order['id']}/approve",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        resp = await client.get(f"/api/v1/listings/{listing_id}")
        assert resp.json()["status"] == "published"


@pytest.mark.anyio
class TestListOrdersFilters:
    async def test_filter_by_multiple_statuses(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        await _create_order(client, listing_id, renter_token)
        order2 = await _create_order(client, listing_id, renter_token, start_offset=10)

        # Offer order2 so it becomes "offered"
        start = _today() + timedelta(days=10)
        end = start + timedelta(days=5)
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order2['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )

        resp = await client.get(
            "/api/v1/orders/?status=pending&status=offered",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        statuses = {item["status"] for item in items}
        assert statuses == {"pending", "offered"}

    async def test_filter_by_listing_id(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        seed_categories: list[Any],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        listing2_id = await _create_second_listing(client, org_id, org_token, seed_categories)
        await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing2_id, renter_token, start_offset=10)

        resp = await client.get(
            f"/api/v1/orders/?listing_id={listing_id}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["listing_id"] == listing_id

    async def test_filter_by_date_range_overlap(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        # Order 1: starts in 1 day, ends in 5 days
        await _create_order(client, listing_id, renter_token, start_offset=1, duration=4)
        # Order 2: starts in 20 days, ends in 24 days
        await _create_order(client, listing_id, renter_token, start_offset=20, duration=4)

        # Filter for dates that only overlap with order 1
        date_from = (_today() + timedelta(days=1)).isoformat()
        date_to = (_today() + timedelta(days=3)).isoformat()
        resp = await client.get(
            f"/api/v1/orders/?date_from={date_from}&date_to={date_to}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1

    async def test_filter_by_date_from_only(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        # Order 1: starts in 1 day, ends in 5 days
        await _create_order(client, listing_id, renter_token, start_offset=1, duration=4)
        # Order 2: starts in 20 days, ends in 24 days
        await _create_order(client, listing_id, renter_token, start_offset=20, duration=4)

        # date_from after order 1 ends -> only order 2
        date_from = (_today() + timedelta(days=10)).isoformat()
        resp = await client.get(
            f"/api/v1/orders/?date_from={date_from}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1

    async def test_search_by_order_id(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order1 = await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing_id, renter_token, start_offset=10)

        resp = await client.get(
            f"/api/v1/orders/?search={order1['id']}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == order1["id"]

    async def test_search_by_listing_name(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        seed_categories: list[Any],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        listing2_id = await _create_second_listing(client, org_id, org_token, seed_categories)
        await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing2_id, renter_token, start_offset=10)

        # "Excavator" matches "Excavator CAT 320" (first listing)
        resp = await client.get(
            "/api/v1/orders/?search=Excavator",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["listing_id"] == listing_id

    async def test_combined_filters(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        seed_categories: list[Any],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        listing2_id = await _create_second_listing(client, org_id, org_token, seed_categories)
        await _create_order(client, listing_id, renter_token)
        order2 = await _create_order(client, listing2_id, renter_token, start_offset=10)

        # Offer order2
        start = _today() + timedelta(days=10)
        end = start + timedelta(days=5)
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order2['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )

        # Filter: status=offered + listing_id=listing2 -> should match order2 only
        resp = await client.get(
            f"/api/v1/orders/?status=offered&listing_id={listing2_id}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == order2["id"]
        assert items[0]["status"] == "offered"

    async def test_org_orders_filter_by_listing_id(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        seed_categories: list[Any],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        listing2_id = await _create_second_listing(client, org_id, org_token, seed_categories)
        await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing2_id, renter_token, start_offset=10)

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/?listing_id={listing_id}",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1


@pytest.mark.anyio
class TestOrderOrdering:
    async def test_user_orders_default_order(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order1 = await _create_order(client, listing_id, renter_token)
        order2 = await _create_order(client, listing_id, renter_token, start_offset=5)

        resp = await client.get(
            "/api/v1/orders/",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        # Default ordering is -updated_at: most recently updated first
        assert items[0]["id"] == order2["id"]
        assert items[1]["id"] == order1["id"]

    async def test_user_orders_order_by_created_at_asc(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order1 = await _create_order(client, listing_id, renter_token)
        order2 = await _create_order(client, listing_id, renter_token, start_offset=5)

        resp = await client.get(
            "/api/v1/orders/?order_by=created_at",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        # Ascending: earliest created first
        assert items[0]["id"] == order1["id"]
        assert items[1]["id"] == order2["id"]

    async def test_user_orders_order_by_requested_start_date(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order1 = await _create_order(client, listing_id, renter_token, start_offset=1)
        order2 = await _create_order(client, listing_id, renter_token, start_offset=10)

        resp = await client.get(
            "/api/v1/orders/?order_by=requested_start_date",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        # Ascending: earlier start date first
        assert items[0]["id"] == order1["id"]
        assert items[1]["id"] == order2["id"]

    async def test_user_orders_invalid_order_by(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        _listing_id, _org_id, _org_token = create_listing

        resp = await client.get(
            "/api/v1/orders/?order_by=invalid",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 422

    async def test_org_orders_order_by_created_at(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order1 = await _create_order(client, listing_id, renter_token)
        order2 = await _create_order(client, listing_id, renter_token, start_offset=5)

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/?order_by=created_at",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        # Ascending: earliest created first
        assert items[0]["id"] == order1["id"]
        assert items[1]["id"] == order2["id"]
        assert items[0]["listing_id"] == listing_id
