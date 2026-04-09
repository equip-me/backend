from datetime import date
from typing import Annotated

from fastapi import Depends, Path, Query

from app.core.dependencies import require_active_user
from app.core.enums import OrderStatus
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.pagination import ordering_dependency
from app.orders.models import Order
from app.users.models import User


async def get_order_or_404(order_id: str = Path()) -> Order:
    order = await Order.get_or_none(id=order_id)
    if order is None:
        raise NotFoundError("Order not found", code="orders.not_found")
    return order


async def require_order_requester(
    order: Annotated[Order, Depends(get_order_or_404)],
    user: Annotated[User, Depends(require_active_user)],
) -> Order:
    if order.requester_id != user.id:
        raise PermissionDeniedError("You are not the requester of this order", code="orders.not_requester")
    return order


async def get_org_order_or_404(org_id: str = Path(), order_id: str = Path()) -> Order:
    order = await Order.get_or_none(id=order_id, organization_id=org_id)
    if order is None:
        raise NotFoundError("Order not found", code="orders.not_found")
    return order


class OrderFilter:
    def __init__(
        self,
        *,
        status: Annotated[list[OrderStatus] | None, Query()] = None,
        listing_id: Annotated[str | None, Query()] = None,
        date_from: Annotated[date | None, Query()] = None,
        date_to: Annotated[date | None, Query()] = None,
        search: Annotated[str | None, Query()] = None,
    ) -> None:
        self.statuses = status
        self.listing_id = listing_id
        self.date_from = date_from
        self.date_to = date_to
        self.search = search


OrderOrdering = ordering_dependency(
    allowed_fields={
        "created_at": "created_at",
        "updated_at": "updated_at",
        "estimated_cost": "estimated_cost",
        "requested_start_date": "requested_start_date",
    },
    default="-updated_at",
)
