from typing import Annotated

from fastapi import Depends, Path

from app.core.dependencies import require_active_user
from app.core.enums import MembershipRole, MembershipStatus
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.orders.models import Order
from app.organizations.models import Membership
from app.users.models import User


async def get_order_or_404(order_id: str = Path()) -> Order:
    order = await Order.get_or_none(id=order_id)
    if order is None:
        raise NotFoundError("Order not found")
    return order


async def require_chat_participant_user(
    order: Annotated[Order, Depends(get_order_or_404)],
    user: Annotated[User, Depends(require_active_user)],
) -> tuple[Order, User]:
    if order.requester_id != user.id:
        raise PermissionDeniedError("Not a chat participant")
    return order, user


async def get_org_order_or_404(org_id: str = Path(), order_id: str = Path()) -> Order:
    order = await Order.get_or_none(id=order_id, organization_id=org_id)
    if order is None:
        raise NotFoundError("Order not found")
    return order


async def require_chat_participant_org(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    user: Annotated[User, Depends(require_active_user)],
) -> tuple[Order, User]:
    membership = await Membership.get_or_none(
        organization_id=order.organization_id,
        user=user,
        status=MembershipStatus.MEMBER,
        role__in=[MembershipRole.ADMIN, MembershipRole.EDITOR],
    )
    if membership is None:
        raise PermissionDeniedError("Organization editor access required")
    return order, user
