from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.listings.models import ListingCategory
from app.reservations.models import Reservation


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _future_date(days: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(days=days)).date().isoformat()


async def _setup_order(
    client: AsyncClient,
    listing_id: str,
    renter_token: str,
    start_days: int = 2,
    end_days: int = 10,
) -> str:
    """Create a PENDING order and return its ID."""
    resp = await client.post(
        "/api/v1/orders/",
        json={
            "listing_id": listing_id,
            "requested_start_date": _future_date(start_days),
            "requested_end_date": _future_date(end_days),
        },
        headers=_auth(renter_token),
    )
    assert resp.status_code == 201
    return str(resp.json()["id"])


async def _offer_order(
    client: AsyncClient,
    org_id: str,
    order_id: str,
    org_token: str,
    start_days: int = 2,
    end_days: int = 10,
    cost: str = "5000.00",
) -> dict[str, Any]:
    resp = await client.patch(
        f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
        json={
            "offered_cost": cost,
            "offered_start_date": _future_date(start_days),
            "offered_end_date": _future_date(end_days),
        },
        headers=_auth(org_token),
    )
    assert resp.status_code == 200
    return dict(resp.json())


async def _accept_order(client: AsyncClient, order_id: str, renter_token: str) -> dict[str, Any]:
    resp = await client.patch(
        f"/api/v1/orders/{order_id}/accept",
        headers=_auth(renter_token),
    )
    assert resp.status_code == 200
    return dict(resp.json())


async def _approve_order(client: AsyncClient, org_id: str, order_id: str, org_token: str) -> dict[str, Any]:
    resp = await client.patch(
        f"/api/v1/organizations/{org_id}/orders/{order_id}/approve",
        headers=_auth(org_token),
    )
    assert resp.status_code == 200
    return dict(resp.json())


@pytest.mark.anyio
class TestOrderHappyPaths:
    async def test_full_lifecycle_pending_to_confirmed(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 1: PENDING -> OFFERED -> ACCEPTED -> CONFIRMED."""
        listing_id, org_id, org_token = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)
        resp = await client.get(f"/api/v1/orders/{order_id}", headers=_auth(renter_token))
        assert resp.json()["status"] == "pending"

        data = await _offer_order(client, org_id, order_id, org_token)
        assert data["status"] == "offered"

        data = await _accept_order(client, order_id, renter_token)
        assert data["status"] == "accepted"

        data = await _approve_order(client, org_id, order_id, org_token)
        assert data["status"] == "confirmed"

        reservation = await Reservation.get_or_none(order_id=order_id)
        assert reservation is not None
        assert reservation.listing_id == listing_id

    async def test_reoffer_from_offered(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 2: Org re-offers with different terms."""
        listing_id, org_id, org_token = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)
        await _offer_order(client, org_id, order_id, org_token, cost="5000.00")
        data = await _offer_order(client, org_id, order_id, org_token, cost="4500.00")
        assert data["status"] == "offered"
        assert data["offered_cost"] == "4500.00"

    async def test_reoffer_from_accepted(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 3: Org re-offers after user already accepted."""
        listing_id, org_id, org_token = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)
        await _offer_order(client, org_id, order_id, org_token, cost="5000.00")
        await _accept_order(client, order_id, renter_token)
        data = await _offer_order(client, org_id, order_id, org_token, cost="6000.00")
        assert data["status"] == "offered"
        assert data["offered_cost"] == "6000.00"

    async def test_estimated_cost_calculation(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 4: Estimated cost = price x days."""
        listing_id, _, _ = create_listing
        order_id = await _setup_order(client, listing_id, renter_token, start_days=2, end_days=6)
        resp = await client.get(f"/api/v1/orders/{order_id}", headers=_auth(renter_token))
        assert resp.json()["estimated_cost"] == "25000.00"

    async def test_list_my_orders(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 5: List user's orders with status filter."""
        listing_id, org_id, org_token = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)
        await _offer_order(client, org_id, order_id, org_token)

        resp = await client.get("/api/v1/orders/", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

        resp = await client.get("/api/v1/orders/?status=offered", headers=_auth(renter_token))
        assert len(resp.json()["items"]) == 1

        resp = await client.get("/api/v1/orders/?status=pending", headers=_auth(renter_token))
        assert len(resp.json()["items"]) == 0

    async def test_list_org_orders(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 6: List organization's orders."""
        listing_id, org_id, org_token = create_listing
        await _setup_order(client, listing_id, renter_token)
        resp = await client.get(f"/api/v1/organizations/{org_id}/orders/", headers=_auth(org_token))
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    async def test_approve_creates_reservation_blocks_overlap(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
        create_user: Any,
    ) -> None:
        """Scenario 7: Approving one order blocks overlapping approval for another."""
        listing_id, org_id, org_token = create_listing

        order1_id = await _setup_order(client, listing_id, renter_token, start_days=5, end_days=15)
        await _offer_order(client, org_id, order1_id, org_token, start_days=5, end_days=15)
        await _accept_order(client, order1_id, renter_token)
        await _approve_order(client, org_id, order1_id, org_token)

        _, renter2_token = await create_user(email="renter2@example.com", phone="+79002223344", name="R2", surname="T")
        order2_id = await _setup_order(client, listing_id, renter2_token, start_days=10, end_days=20)
        await _offer_order(client, org_id, order2_id, org_token, start_days=10, end_days=20)
        await _accept_order(client, order2_id, renter2_token)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order2_id}/approve",
            headers=_auth(org_token),
        )
        assert resp.status_code == 400
        assert "overlapping" in resp.json()["detail"].lower()


@pytest.mark.anyio
class TestOrderNegativeCases:
    async def test_order_unpublished_listing(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
        renter_token: str,
    ) -> None:
        org_data, org_token = verified_org
        org_id = org_data["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Hidden", "category_id": seed_categories[0].id, "price": 100.00},
            headers=_auth(org_token),
        )
        listing_id = resp.json()["id"]
        resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": _future_date(1),
                "requested_end_date": _future_date(5),
            },
            headers=_auth(renter_token),
        )
        assert resp.status_code == 400

    async def test_order_past_start_date(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _, _ = create_listing
        yesterday = (datetime.now(tz=UTC) - timedelta(days=1)).date().isoformat()
        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": yesterday, "requested_end_date": _future_date(5)},
            headers=_auth(renter_token),
        )
        assert resp.status_code == 400

    async def test_accept_from_wrong_status(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _, _ = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)
        resp = await client.patch(f"/api/v1/orders/{order_id}/accept", headers=_auth(renter_token))
        assert resp.status_code == 400

    async def test_approve_from_wrong_status(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)
        await _offer_order(client, org_id, order_id, org_token)
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/approve",
            headers=_auth(org_token),
        )
        assert resp.status_code == 400

    async def test_non_requester_cannot_accept(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
        create_user: Any,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)
        await _offer_order(client, org_id, order_id, org_token)
        _, other_token = await create_user(email="other@example.com", phone="+79003334455", name="O", surname="T")
        resp = await client.patch(f"/api/v1/orders/{order_id}/accept", headers=_auth(other_token))
        assert resp.status_code == 403
