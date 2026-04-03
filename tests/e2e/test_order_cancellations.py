from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.reservations.models import Reservation


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _future_date(days: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(days=days)).date().isoformat()


async def _create_pending_order(
    client: AsyncClient,
    listing_id: str,
    renter_token: str,
) -> str:
    resp = await client.post(
        "/api/v1/orders/",
        json={
            "listing_id": listing_id,
            "requested_start_date": _future_date(2),
            "requested_end_date": _future_date(10),
        },
        headers=_auth(renter_token),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _advance_to_offered(
    client: AsyncClient,
    org_id: str,
    order_id: str,
    org_token: str,
) -> None:
    resp = await client.patch(
        f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
        json={
            "offered_cost": "5000.00",
            "offered_start_date": _future_date(2),
            "offered_end_date": _future_date(10),
        },
        headers=_auth(org_token),
    )
    assert resp.status_code == 200


async def _advance_to_accepted(
    client: AsyncClient,
    org_id: str,
    order_id: str,
    org_token: str,
    renter_token: str,
) -> None:
    await _advance_to_offered(client, org_id, order_id, org_token)
    resp = await client.patch(f"/api/v1/orders/{order_id}/accept", headers=_auth(renter_token))
    assert resp.status_code == 200


async def _advance_to_confirmed(
    client: AsyncClient,
    org_id: str,
    order_id: str,
    org_token: str,
    renter_token: str,
) -> None:
    await _advance_to_accepted(client, org_id, order_id, org_token, renter_token)
    resp = await client.patch(
        f"/api/v1/organizations/{org_id}/orders/{order_id}/approve",
        headers=_auth(org_token),
    )
    assert resp.status_code == 200


@pytest.mark.anyio
class TestUserCancellations:
    async def test_cancel_pending(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, _, _ = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

    async def test_cancel_offered(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_offered(client, org_id, order_id, org_token)
        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

    async def test_cancel_accepted(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_accepted(client, org_id, order_id, org_token, renter_token)
        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

    async def test_cancel_confirmed_deletes_reservation(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_confirmed(client, org_id, order_id, org_token, renter_token)
        assert await Reservation.filter(order_id=order_id).exists()
        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"
        assert not await Reservation.filter(order_id=order_id).exists()


@pytest.mark.anyio
class TestOrgCancellations:
    async def test_org_cancel_pending(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"

    async def test_org_cancel_offered(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_offered(client, org_id, order_id, org_token)
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"

    async def test_org_cancel_accepted(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_accepted(client, org_id, order_id, org_token, renter_token)
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"

    async def test_org_cancel_confirmed_deletes_reservation(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_confirmed(client, org_id, order_id, org_token, renter_token)
        assert await Reservation.filter(order_id=order_id).exists()
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"
        assert not await Reservation.filter(order_id=order_id).exists()


@pytest.mark.anyio
class TestCancellationNegativeCases:
    async def test_cancel_terminal_order_fails(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, _, _ = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 400

    async def test_non_requester_cannot_cancel(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str, create_user: Any
    ) -> None:
        listing_id, _, _ = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        _, other_token = await create_user(email="other@example.com", phone="+79003334455", name="O", surname="T")
        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(other_token))
        assert resp.status_code == 403

    async def test_wrong_org_cannot_cancel(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, _ = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(renter_token),
        )
        assert resp.status_code in (403, 404)
