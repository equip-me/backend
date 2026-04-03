from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.enums import OrderStatus
from app.orders.models import Order
from app.worker.orders import activate_order, expire_order, finish_order, order_sweep_cron


def _empty_ctx() -> dict[str, Any]:
    return {}


@pytest.fixture
async def pending_order(
    create_listing: tuple[str, str, str],
    renter_token: str,
    client: AsyncClient,
) -> Order:
    """Create a PENDING order via API and return the ORM object."""
    listing_id, _org_id, _org_token = create_listing
    start = (datetime.now(tz=UTC) + timedelta(days=2)).date()
    end = (datetime.now(tz=UTC) + timedelta(days=10)).date()
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
    return await Order.get(id=resp.json()["id"])


class TestExpireOrder:
    async def test_expires_pending_order(self, pending_order: Order) -> None:
        pending_order.requested_start_date = date(2026, 1, 1)
        await pending_order.save()

        await expire_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.EXPIRED

    async def test_skips_non_expirable_status(self, pending_order: Order) -> None:
        pending_order.status = OrderStatus.CONFIRMED
        await pending_order.save()

        await expire_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.CONFIRMED

    async def test_skips_missing_order(self) -> None:
        await expire_order(_empty_ctx(), "ZZZZZZ")


class TestActivateOrder:
    async def test_activates_confirmed_order(self, pending_order: Order) -> None:
        pending_order.status = OrderStatus.CONFIRMED
        pending_order.offered_start_date = date(2026, 1, 1)
        pending_order.offered_end_date = date(2026, 1, 10)
        await pending_order.save()

        await activate_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.ACTIVE

    async def test_skips_non_confirmed(self, pending_order: Order) -> None:
        await activate_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.PENDING


class TestFinishOrder:
    async def test_finishes_active_order(self, pending_order: Order) -> None:
        pending_order.status = OrderStatus.ACTIVE
        pending_order.offered_start_date = date(2026, 1, 1)
        pending_order.offered_end_date = date(2026, 1, 10)
        await pending_order.save()

        await finish_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.FINISHED

    async def test_skips_non_active(self, pending_order: Order) -> None:
        await finish_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.PENDING


class TestOrderSweepCron:
    async def test_sweep_expires_stale_pending(self, pending_order: Order) -> None:
        pending_order.requested_start_date = date(2026, 1, 1)
        await pending_order.save()

        await order_sweep_cron(_empty_ctx())

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.EXPIRED

    async def test_sweep_activates_confirmed(self, pending_order: Order) -> None:
        pending_order.status = OrderStatus.CONFIRMED
        pending_order.offered_start_date = date(2026, 1, 1)
        pending_order.offered_end_date = date(2026, 12, 31)
        await pending_order.save()

        await order_sweep_cron(_empty_ctx())

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.ACTIVE

    async def test_sweep_finishes_active(self, pending_order: Order) -> None:
        pending_order.status = OrderStatus.ACTIVE
        pending_order.offered_start_date = date(2026, 1, 1)
        pending_order.offered_end_date = date(2026, 1, 10)
        await pending_order.save()

        await order_sweep_cron(_empty_ctx())

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.FINISHED
