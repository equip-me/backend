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
from app.orders.state_machine import maybe_auto_transition, transition
from app.users.models import User


def _record_transition(order_id: str, old_status: OrderStatus, new_status: OrderStatus) -> None:
    order_transitions.add(1, {"from_status": old_status.value, "to_status": new_status.value})
    emit_event("order.status_changed", order_id=order_id, old_status=old_status.value, new_status=new_status.value)


async def _apply_auto_transition(order: Order) -> Order:
    # TODO: Replace with Temporal workflow for automatic order status transitions
    new_status = maybe_auto_transition(
        status=order.status,
        offered_start_date=order.offered_start_date,
        offered_end_date=order.offered_end_date,
        today=datetime.now(UTC).date(),
    )
    if new_status is None:
        return order

    order.status = new_status
    await order.save()

    # Note: fetch_related may issue a redundant query if listing was already prefetch_related
    # in the list endpoints. Acceptable until Temporal replaces lazy evaluation.
    await order.fetch_related("listing")
    listing: Listing = order.listing

    if new_status == OrderStatus.ACTIVE:
        listing.status = ListingStatus.IN_RENT
        await listing.save()
    elif new_status == OrderStatus.FINISHED:
        listing.status = ListingStatus.PUBLISHED
        await listing.save()

    return order


async def _to_read(order: Order) -> OrderRead:
    order = await _apply_auto_transition(order)
    return OrderRead.model_validate(order)


@traced
async def create_order(user: User, data: OrderCreate) -> OrderRead:
    listing = await Listing.get_or_none(id=data.listing_id).select_related("organization")
    if listing is None:
        raise NotFoundError("Listing not found")

    if listing.status != ListingStatus.PUBLISHED:
        raise AppValidationError("Listing is not available for ordering")

    if listing.organization.status != OrganizationStatus.VERIFIED:
        raise PermissionDeniedError("Organization is not verified")

    if data.requested_start_date < datetime.now(UTC).date():
        raise AppValidationError("requested_start_date cannot be in the past")

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
    # _to_read is safe here: OFFERED status won't trigger auto-transition
    return await _to_read(order)


@traced
async def reject_order(order: Order) -> OrderRead:
    old_status = order.status
    order.status = transition(order.status, OrderAction.REJECT_BY_ORG)
    await order.save()
    _record_transition(order.id, old_status, order.status)
    # _to_read is safe here: REJECTED is terminal, auto-transition won't fire
    return await _to_read(order)


@traced
async def confirm_order(order: Order) -> OrderRead:
    old_status = order.status
    order.status = transition(order.status, OrderAction.CONFIRM_BY_USER)
    await order.save()
    _record_transition(order.id, old_status, order.status)
    return await _to_read(order)


@traced
async def decline_order(order: Order) -> OrderRead:
    old_status = order.status
    order.status = transition(order.status, OrderAction.DECLINE_BY_USER)
    await order.save()
    _record_transition(order.id, old_status, order.status)
    # _to_read is safe here: DECLINED is terminal, auto-transition won't fire
    return await _to_read(order)


async def _cancel_order(order: Order, action: OrderAction) -> OrderRead:
    old_status = order.status
    order.status = transition(order.status, action)
    await order.save()

    await order.fetch_related("listing")
    listing: Listing = order.listing
    if listing.status == ListingStatus.IN_RENT:
        listing.status = ListingStatus.PUBLISHED
        await listing.save()

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
    return await _to_read(order)


@traced
async def list_user_orders(
    user: User,
    params: CursorParams,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(requester=user).prefetch_related("listing")
    if status:
        qs = qs.filter(status=status)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
    order_reads = [await _to_read(order) for order in items]
    return PaginatedResponse(items=order_reads, next_cursor=next_cursor, has_more=has_more)


@traced
async def list_org_orders(
    org_id: str,
    params: CursorParams,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(organization_id=org_id).prefetch_related("listing")
    if status:
        qs = qs.filter(status=status)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
    order_reads = [await _to_read(order) for order in items]
    return PaginatedResponse(items=order_reads, next_cursor=next_cursor, has_more=has_more)
