from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies import require_active_user
from app.core.enums import OrderStatus
from app.core.pagination import CursorParams, PaginatedResponse
from app.orders import service
from app.orders.dependencies import get_org_order_or_404, require_order_requester
from app.orders.models import Order
from app.orders.schemas import OrderCreate, OrderOffer, OrderRead
from app.organizations.dependencies import require_org_editor
from app.organizations.models import Membership
from app.users.models import User

router = APIRouter(prefix="/api/v1", tags=["Orders"])


# --- User (renter) endpoints ---


@router.post("/orders/", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    user: Annotated[User, Depends(require_active_user)],
) -> OrderRead:
    return await service.create_order(user, data)


@router.get("/orders/", response_model=PaginatedResponse[OrderRead])
async def list_my_orders(
    user: Annotated[User, Depends(require_active_user)],
    cursor: str | None = None,
    limit: int = 20,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_user_orders(user, params, status=status)


@router.get("/orders/{order_id}", response_model=OrderRead)
async def get_my_order(
    order: Annotated[Order, Depends(require_order_requester)],
) -> OrderRead:
    return await service.get_order(order)


@router.patch("/orders/{order_id}/accept", response_model=OrderRead)
async def accept_order(
    order: Annotated[Order, Depends(require_order_requester)],
) -> OrderRead:
    return await service.accept_order(order)


@router.patch("/orders/{order_id}/cancel", response_model=OrderRead)
async def cancel_order_by_user(
    order: Annotated[Order, Depends(require_order_requester)],
) -> OrderRead:
    return await service.cancel_order_by_user(order)


# --- Organization (owner) endpoints ---


@router.get("/organizations/{org_id}/orders/", response_model=PaginatedResponse[OrderRead])
async def list_org_orders(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_editor)],
    cursor: str | None = None,
    limit: int = 20,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_org_orders(org_id, params, status=status)


@router.get("/organizations/{org_id}/orders/{order_id}", response_model=OrderRead)
async def get_org_order(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.get_order(order)


@router.patch("/organizations/{org_id}/orders/{order_id}/offer", response_model=OrderRead)
async def offer_order(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    data: OrderOffer,
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.offer_order(order, data)


@router.patch("/organizations/{org_id}/orders/{order_id}/approve", response_model=OrderRead)
async def approve_order(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.approve_order(order)


@router.patch("/organizations/{org_id}/orders/{order_id}/cancel", response_model=OrderRead)
async def cancel_order_by_org(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.cancel_order_by_org(order)
