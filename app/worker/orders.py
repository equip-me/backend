import logging
from datetime import UTC, datetime
from typing import Any

from app.core.enums import OrderAction, OrderStatus
from app.core.exceptions import AppValidationError
from app.orders.models import Order
from app.orders.service import _record_transition
from app.orders.state_machine import transition

logger = logging.getLogger(__name__)

_EXPIRABLE_STATUSES = {OrderStatus.PENDING, OrderStatus.OFFERED, OrderStatus.ACCEPTED}


async def _ensure_db() -> None:
    from tortoise import Tortoise

    from app.core.database import get_tortoise_config

    if not Tortoise._inited:
        await Tortoise.init(config=get_tortoise_config())


async def expire_order(_ctx: dict[str, Any], order_id: str) -> None:
    await _ensure_db()
    order = await Order.get_or_none(id=order_id)
    if order is None:
        logger.warning("expire_order: order %s not found", order_id)
        return
    if order.status not in _EXPIRABLE_STATUSES:
        logger.info("expire_order: order %s already in status %s, skipping", order_id, order.status.value)
        return
    try:
        old_status = order.status
        order.status = transition(order.status, OrderAction.EXPIRE)
        await order.save()
        await _record_transition(order.id, old_status, order.status)
        logger.info("Expired order %s: %s → %s", order_id, old_status.value, order.status.value)
    except AppValidationError:
        logger.warning("expire_order: cannot expire order %s in status %s", order_id, order.status.value)


async def activate_order(_ctx: dict[str, Any], order_id: str) -> None:
    await _ensure_db()
    order = await Order.get_or_none(id=order_id)
    if order is None:
        logger.warning("activate_order: order %s not found", order_id)
        return
    if order.status != OrderStatus.CONFIRMED:
        logger.info("activate_order: order %s in status %s, skipping", order_id, order.status.value)
        return
    try:
        old_status = order.status
        order.status = transition(order.status, OrderAction.ACTIVATE)
        await order.save()
        await _record_transition(order.id, old_status, order.status)
        logger.info("Activated order %s: %s → %s", order_id, old_status.value, order.status.value)

        # Schedule finish job
        if order.offered_end_date is not None:
            from app.worker.settings import get_arq_pool

            pool = await get_arq_pool()
            from datetime import timedelta

            finish_at = datetime.combine(order.offered_end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            await pool.enqueue_job("finish_order", order.id, _defer_until=finish_at)

    except AppValidationError:
        logger.warning("activate_order: cannot activate order %s in status %s", order_id, order.status.value)


async def finish_order(_ctx: dict[str, Any], order_id: str) -> None:
    await _ensure_db()
    order = await Order.get_or_none(id=order_id)
    if order is None:
        logger.warning("finish_order: order %s not found", order_id)
        return
    if order.status != OrderStatus.ACTIVE:
        logger.info("finish_order: order %s in status %s, skipping", order_id, order.status.value)
        return
    try:
        old_status = order.status
        order.status = transition(order.status, OrderAction.FINISH)
        await order.save()
        await _record_transition(order.id, old_status, order.status)
        logger.info("Finished order %s: %s → %s", order_id, old_status.value, order.status.value)
    except AppValidationError:
        logger.warning("finish_order: cannot finish order %s in status %s", order_id, order.status.value)


async def order_sweep_cron(_ctx: dict[Any, Any]) -> None:
    """Daily safety-net sweep for order auto-transitions."""
    await _ensure_db()
    today = datetime.now(UTC).date()

    # Expire stale orders
    expired_count = 0
    pending_stale = await Order.filter(status=OrderStatus.PENDING, requested_start_date__lt=today)
    for order in pending_stale:
        order.status = OrderStatus.EXPIRED
        await order.save()
        expired_count += 1

    offered_stale = await Order.filter(status=OrderStatus.OFFERED, offered_start_date__lt=today)
    for order in offered_stale:
        order.status = OrderStatus.EXPIRED
        await order.save()
        expired_count += 1

    accepted_stale = await Order.filter(status=OrderStatus.ACCEPTED, offered_start_date__lt=today)
    for order in accepted_stale:
        order.status = OrderStatus.EXPIRED
        await order.save()
        expired_count += 1

    # Activate confirmed orders
    activated_count = 0
    confirmed_ready = await Order.filter(status=OrderStatus.CONFIRMED, offered_start_date__lte=today)
    for order in confirmed_ready:
        order.status = OrderStatus.ACTIVE
        await order.save()
        activated_count += 1

    # Finish active orders
    finished_count = 0
    active_done = await Order.filter(status=OrderStatus.ACTIVE, offered_end_date__lt=today)
    for order in active_done:
        order.status = OrderStatus.FINISHED
        await order.save()
        finished_count += 1

    logger.info(
        "Order sweep: expired=%d, activated=%d, finished=%d",
        expired_count,
        activated_count,
        finished_count,
    )
