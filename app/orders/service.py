from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import ListingStatus, OrderAction, OrderStatus, OrganizationStatus
from app.core.exceptions import AppValidationError, NotFoundError, PermissionDeniedError
from app.core.identifiers import create_with_short_id
from app.listings.models import Listing
from app.orders.models import Order
from app.orders.schemas import OrderCreate, OrderOffer, OrderRead
from app.orders.state_machine import maybe_auto_transition, transition
from app.users.models import User


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
    return OrderRead.model_validate(order)


async def offer_order(order: Order, data: OrderOffer) -> OrderRead:
    new_status = transition(order.status, OrderAction.OFFER)
    order.status = new_status
    order.offered_cost = data.offered_cost
    order.offered_start_date = data.offered_start_date
    order.offered_end_date = data.offered_end_date
    await order.save()
    return OrderRead.model_validate(order)


async def reject_order(order: Order) -> OrderRead:
    order.status = transition(order.status, OrderAction.REJECT)
    await order.save()
    return OrderRead.model_validate(order)


async def confirm_order(order: Order) -> OrderRead:
    order.status = transition(order.status, OrderAction.CONFIRM)
    await order.save()
    return await _to_read(order)


async def decline_order(order: Order) -> OrderRead:
    order.status = transition(order.status, OrderAction.DECLINE)
    await order.save()
    return OrderRead.model_validate(order)


async def _cancel_order(order: Order, action: OrderAction) -> OrderRead:
    order.status = transition(order.status, action)
    await order.save()

    await order.fetch_related("listing")
    listing: Listing = order.listing
    if listing.status == ListingStatus.IN_RENT:
        listing.status = ListingStatus.PUBLISHED
        await listing.save()

    return OrderRead.model_validate(order)


async def cancel_order_by_user(order: Order) -> OrderRead:
    return await _cancel_order(order, OrderAction.CANCEL_BY_USER)


async def cancel_order_by_org(order: Order) -> OrderRead:
    return await _cancel_order(order, OrderAction.CANCEL_BY_ORG)


async def get_order(order: Order) -> OrderRead:
    return await _to_read(order)


async def list_user_orders(user: User) -> list[OrderRead]:
    orders = await Order.filter(requester=user).order_by("-updated_at")
    return [await _to_read(order) for order in orders]


async def list_org_orders(org_id: str) -> list[OrderRead]:
    orders = await Order.filter(organization_id=org_id).order_by("-updated_at")
    return [await _to_read(order) for order in orders]
