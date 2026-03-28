from __future__ import annotations

from datetime import date

from app.core.enums import OrderAction, OrderStatus
from app.core.exceptions import AppValidationError

_TRANSITIONS: dict[tuple[OrderStatus, OrderAction], OrderStatus] = {
    (OrderStatus.PENDING, OrderAction.OFFER): OrderStatus.OFFERED,
    (OrderStatus.PENDING, OrderAction.REJECT): OrderStatus.REJECTED,
    (OrderStatus.OFFERED, OrderAction.OFFER): OrderStatus.OFFERED,
    (OrderStatus.OFFERED, OrderAction.CONFIRM): OrderStatus.CONFIRMED,
    (OrderStatus.OFFERED, OrderAction.DECLINE): OrderStatus.DECLINED,
    (OrderStatus.CONFIRMED, OrderAction.ACTIVATE): OrderStatus.ACTIVE,
    (OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_USER): OrderStatus.CANCELED_BY_USER,
    (OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_ORG): OrderStatus.CANCELED_BY_ORGANIZATION,
    (OrderStatus.ACTIVE, OrderAction.FINISH): OrderStatus.FINISHED,
    (OrderStatus.ACTIVE, OrderAction.CANCEL_BY_USER): OrderStatus.CANCELED_BY_USER,
    (OrderStatus.ACTIVE, OrderAction.CANCEL_BY_ORG): OrderStatus.CANCELED_BY_ORGANIZATION,
}


def transition(current: OrderStatus, action: OrderAction) -> OrderStatus:
    key = (current, action)
    if key not in _TRANSITIONS:
        msg = f"Cannot {action.value} order in status {current.value}"
        raise AppValidationError(msg)
    return _TRANSITIONS[key]


# NOTE: Replace with Temporal workflow for automatic order status transitions
def maybe_auto_transition(
    *,
    status: OrderStatus,
    offered_start_date: date | None,
    offered_end_date: date | None,
    today: date,
) -> OrderStatus | None:
    current = status

    if current == OrderStatus.CONFIRMED and offered_start_date is not None and today >= offered_start_date:
        current = OrderStatus.ACTIVE

    if current == OrderStatus.ACTIVE and offered_end_date is not None and today > offered_end_date:
        current = OrderStatus.FINISHED

    if current == status:
        return None
    return current
