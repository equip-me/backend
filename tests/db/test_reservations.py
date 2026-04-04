from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.exceptions import AppValidationError
from app.listings.models import ListingCategory
from app.reservations import service as reservation_service
from app.reservations.models import Reservation


@pytest.fixture
async def listing_id(
    client: AsyncClient,
    verified_org: tuple[dict[str, Any], str],
    seed_categories: list[ListingCategory],
) -> str:
    """Create a published listing and return its ID."""
    org_data, org_token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/listings/",
        json={
            "name": "Test Listing",
            "category_id": category_id,
            "price": 1000.00,
        },
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert resp.status_code == 201
    listing_id: str = resp.json()["id"]

    await client.patch(
        f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
        json={"status": "published"},
        headers={"Authorization": f"Bearer {org_token}"},
    )
    return listing_id


class TestCreateReservation:
    async def test_creates_reservation(self, listing_id: str) -> None:
        reservation = await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        assert reservation.listing_id == listing_id
        assert reservation.order_id == "ORD001"
        assert reservation.start_date == date(2026, 5, 1)
        assert reservation.end_date == date(2026, 5, 10)

    async def test_rejects_overlapping_dates(self, listing_id: str) -> None:
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        with pytest.raises(AppValidationError, match="overlapping reservation"):
            await reservation_service.create_reservation(
                listing_id=listing_id,
                order_id="ORD002",
                start_date=date(2026, 5, 5),
                end_date=date(2026, 5, 15),
            )

    async def test_allows_adjacent_dates(self, listing_id: str) -> None:
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        reservation = await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD002",
            start_date=date(2026, 5, 11),
            end_date=date(2026, 5, 20),
        )
        assert reservation.order_id == "ORD002"

    async def test_allows_same_dates_different_listing(
        self,
        listing_id: str,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, org_token = verified_org
        org_id = org_data["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Other Listing", "category_id": seed_categories[0].id, "price": 2000.00},
            headers={"Authorization": f"Bearer {org_token}"},
        )
        other_listing_id: str = resp.json()["id"]

        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        reservation = await reservation_service.create_reservation(
            listing_id=other_listing_id,
            order_id="ORD002",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        assert reservation.listing_id == other_listing_id


class TestDeleteReservation:
    async def test_deletes_by_order_id(self, listing_id: str) -> None:
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        deleted = await reservation_service.delete_reservation_by_order("ORD001")
        assert deleted is True
        assert await Reservation.filter(order_id="ORD001").count() == 0

    async def test_delete_nonexistent_returns_false(self) -> None:
        deleted = await reservation_service.delete_reservation_by_order("NONEXIST")
        assert deleted is False


class TestListFutureReservations:
    async def test_returns_future_reservations(self, listing_id: str) -> None:
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD002",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 10),
        )
        results = await reservation_service.list_future_reservations(
            listing_id=listing_id,
            today=date(2026, 5, 5),
        )
        assert len(results) == 2

    async def test_excludes_past_reservations(self, listing_id: str) -> None:
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 10),
        )
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD002",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 10),
        )
        results = await reservation_service.list_future_reservations(
            listing_id=listing_id,
            today=date(2026, 5, 5),
        )
        assert len(results) == 1
        assert results[0].order_id == "ORD002"
