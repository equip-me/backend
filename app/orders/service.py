from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import ListingStatus, OrderAction, OrderStatus, OrganizationStatus
from app.core.exceptions import AppValidationError, NotFoundError, PermissionDeniedError
from app.core.identifiers import create_with_short_id
from app.core.pagination import CursorParams, PaginatedResponse, paginate
from app.listings.models import Listing
from app.observability.events import emit_event
from app.observability.metrics import order_transitions, orders_created
from app.observability.tracing import traced
from app.orders.models import Order
from app.orders.schemas import OrderCreate, OrderOffer, OrderRead
from app.orders.state_machine import transition
from app.reservations import service as reservation_service
from app.users.models import User


def _record_transition(order_id: str, old_status: OrderStatus, new_status: OrderStatus) -> None:
    order_transitions.add(1, {"from_status": old_status.value, "to_status": new_status.value})
    emit_event("order.status_changed", order_id=order_id, old_status=old_status.value, new_status=new_status.value)


async def _schedule_expire_job(order: Order, expire_date: datetime) -> None:
    """Schedule a deferred ARQ job to expire the order at the given date."""
    from app.worker.settings import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job("expire_order", order.id, _defer_until=expire_date)


async def _schedule_activate_job(order: Order) -> None:
    """Schedule a deferred ARQ job to activate the order on offered_start_date."""
    from app.worker.settings import get_arq_pool

    if order.offered_start_date is None:
        return
    pool = await get_arq_pool()
    activate_at = datetime.combine(order.offered_start_date, datetime.min.time(), tzinfo=UTC)
    await pool.enqueue_job("activate_order", order.id, _defer_until=activate_at)


async def _schedule_finish_job(order: Order) -> None:
    """Schedule a deferred ARQ job to finish the order after offered_end_date."""
    from app.worker.settings import get_arq_pool

    if order.offered_end_date is None:
        return
    pool = await get_arq_pool()
    from datetime import timedelta

    finish_at = datetime.combine(order.offered_end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    await pool.enqueue_job("finish_order", order.id, _defer_until=finish_at)


@traced
async def create_order(user: User, data: OrderCreate) -> OrderRead:
    listing = await Listing.get_or_none(id=data.listing_id).select_related("organization")
    if listing is None:
        raise NotFoundError("Listing not found", code="listings.not_found")

    if listing.status != ListingStatus.PUBLISHED:
        raise AppValidationError("Listing is not available for ordering", code="orders.listing_unavailable")

    if listing.organization.status != OrganizationStatus.VERIFIED:
        raise PermissionDeniedError("Organization is not verified", code="orders.org_not_verified")

    if data.requested_start_date < datetime.now(UTC).date():
        raise AppValidationError("requested_start_date cannot be in the past", code="orders.start_date_in_past")

    days = Decimal((data.requested_end_date - data.requested_start_date).days + 1)
    price = Decimal(str(listing.price))
    estimated_cost = (price * days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    order = await create_with_short_id(
        Order,
        listing=listing,
        organization=listing.organization,
        requester=user,
        requested_start_date=data.requested_start_date,
        requested_end_date=data.requested_end_date,
        estimated_cost=estimated_cost,
    )
    orders_created.add(1, {"org_id": listing.organization.id, "listing_id": data.listing_id})
    emit_event("order.created", order_id=order.id, listing_id=data.listing_id, user_id=user.id)

    expire_at = datetime.combine(data.requested_start_date, datetime.min.time(), tzinfo=UTC)
    await _schedule_expire_job(order, expire_at)

    return OrderRead.model_validate(order)


@traced
async def offer_order(order: Order, data: OrderOffer) -> OrderRead:
    old_status = order.status
    new_status = transition(order.status, OrderAction.OFFER_BY_ORG)
    order.status = new_status
    order.offered_cost = data.offered_cost
    order.offered_start_date = data.offered_start_date
    order.offered_end_date = data.offered_end_date
    await order.save()
    _record_transition(order.id, old_status, new_status)

    expire_at = datetime.combine(data.offered_start_date, datetime.min.time(), tzinfo=UTC)
    await _schedule_expire_job(order, expire_at)

    return OrderRead.model_validate(order)


@traced
async def accept_order(order: Order) -> OrderRead:
    old_status = order.status
    order.status = transition(order.status, OrderAction.ACCEPT_BY_USER)
    await order.save()
    _record_transition(order.id, old_status, order.status)
    return OrderRead.model_validate(order)


@traced
async def approve_order(order: Order) -> OrderRead:
    old_status = order.status
    order.status = transition(order.status, OrderAction.APPROVE_BY_ORG)

    if order.offered_start_date is None or order.offered_end_date is None:
        raise AppValidationError("Cannot approve order without offered dates", code="orders.no_offered_dates")

    await reservation_service.create_reservation(
        listing_id=order.listing_id,
        order_id=order.id,
        start_date=order.offered_start_date,
        end_date=order.offered_end_date,
    )

    await order.save()
    _record_transition(order.id, old_status, order.status)

    await _schedule_activate_job(order)

    return OrderRead.model_validate(order)


async def _cancel_order(order: Order, action: OrderAction) -> OrderRead:
    old_status = order.status
    order.status = transition(order.status, action)
    await order.save()

    if old_status in (OrderStatus.CONFIRMED, OrderStatus.ACTIVE):
        await reservation_service.delete_reservation_by_order(order.id)

    _record_transition(order.id, old_status, order.status)
    return OrderRead.model_validate(order)


@traced
async def cancel_order_by_user(order: Order) -> OrderRead:
    return await _cancel_order(order, OrderAction.CANCEL_BY_USER)


@traced
async def cancel_order_by_org(order: Order) -> OrderRead:
    return await _cancel_order(order, OrderAction.CANCEL_BY_ORG)


@traced
async def get_order(order: Order) -> OrderRead:
    return OrderRead.model_validate(order)


@traced
async def list_user_orders(
    user: User,
    params: CursorParams,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(requester=user)
    if status:
        qs = qs.filter(status=status)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
    order_reads = [OrderRead.model_validate(order) for order in items]
    return PaginatedResponse(items=order_reads, next_cursor=next_cursor, has_more=has_more)


@traced
async def list_org_orders(
    org_id: str,
    params: CursorParams,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(organization_id=org_id)
    if status:
        qs = qs.filter(status=status)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
    order_reads = [OrderRead.model_validate(order) for order in items]
    return PaginatedResponse(items=order_reads, next_cursor=next_cursor, has_more=has_more)
