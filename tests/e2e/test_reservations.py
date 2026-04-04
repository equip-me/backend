from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.reservations.models import Reservation


@pytest.fixture
async def listing_with_reservation(
    create_listing: tuple[str, str, str],
) -> tuple[str, str, str]:
    """Create a listing with one reservation. Returns (listing_id, org_id, org_token)."""
    listing_id, org_id, org_token = create_listing
    start = (datetime.now(tz=UTC) + timedelta(days=5)).date()
    end = (datetime.now(tz=UTC) + timedelta(days=15)).date()
    await Reservation.create(
        listing_id=listing_id,
        order_id="FAKE01",
        start_date=start,
        end_date=end,
    )
    return listing_id, org_id, org_token


class TestListReservations:
    async def test_returns_future_reservations(
        self,
        client: AsyncClient,
        listing_with_reservation: tuple[str, str, str],
    ) -> None:
        listing_id, _, _ = listing_with_reservation
        resp = await client.get(f"/api/v1/listings/{listing_id}/reservations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "order_id" not in data[0]
        assert "listing_id" in data[0]
        assert "start_date" in data[0]
        assert "end_date" in data[0]

    async def test_excludes_past_reservations(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
    ) -> None:
        listing_id, _, _ = create_listing
        past_end = (datetime.now(tz=UTC) - timedelta(days=1)).date()
        past_start = (datetime.now(tz=UTC) - timedelta(days=10)).date()
        await Reservation.create(
            listing_id=listing_id,
            order_id="PAST01",
            start_date=past_start,
            end_date=past_end,
        )
        resp = await client.get(f"/api/v1/listings/{listing_id}/reservations")
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    async def test_no_auth_required(
        self,
        client: AsyncClient,
        listing_with_reservation: tuple[str, str, str],
    ) -> None:
        listing_id, _, _ = listing_with_reservation
        resp = await client.get(f"/api/v1/listings/{listing_id}/reservations")
        assert resp.status_code == 200

    async def test_empty_for_no_reservations(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
    ) -> None:
        listing_id, _, _ = create_listing
        resp = await client.get(f"/api/v1/listings/{listing_id}/reservations")
        assert resp.status_code == 200
        assert resp.json() == []
