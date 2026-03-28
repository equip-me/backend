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

        await client.patch(
            f"/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {org_token}"},
        )

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
