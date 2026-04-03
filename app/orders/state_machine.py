from app.core.enums import OrderAction, OrderStatus
from app.core.exceptions import AppValidationError

_TRANSITIONS: dict[tuple[OrderStatus, OrderAction], OrderStatus] = {
    # PENDING
    (OrderStatus.PENDING, OrderAction.OFFER_BY_ORG): OrderStatus.OFFERED,
    (OrderStatus.PENDING, OrderAction.CANCEL_BY_USER): OrderStatus.CANCELED_BY_USER,
    (OrderStatus.PENDING, OrderAction.CANCEL_BY_ORG): OrderStatus.CANCELED_BY_ORGANIZATION,
    (OrderStatus.PENDING, OrderAction.EXPIRE): OrderStatus.EXPIRED,
    # OFFERED
    (OrderStatus.OFFERED, OrderAction.OFFER_BY_ORG): OrderStatus.OFFERED,
    (OrderStatus.OFFERED, OrderAction.ACCEPT_BY_USER): OrderStatus.ACCEPTED,
    (OrderStatus.OFFERED, OrderAction.CANCEL_BY_USER): OrderStatus.CANCELED_BY_USER,
    (OrderStatus.OFFERED, OrderAction.CANCEL_BY_ORG): OrderStatus.CANCELED_BY_ORGANIZATION,
    (OrderStatus.OFFERED, OrderAction.EXPIRE): OrderStatus.EXPIRED,
    # ACCEPTED
    (OrderStatus.ACCEPTED, OrderAction.OFFER_BY_ORG): OrderStatus.OFFERED,
    (OrderStatus.ACCEPTED, OrderAction.APPROVE_BY_ORG): OrderStatus.CONFIRMED,
    (OrderStatus.ACCEPTED, OrderAction.CANCEL_BY_USER): OrderStatus.CANCELED_BY_USER,
    (OrderStatus.ACCEPTED, OrderAction.CANCEL_BY_ORG): OrderStatus.CANCELED_BY_ORGANIZATION,
    (OrderStatus.ACCEPTED, OrderAction.EXPIRE): OrderStatus.EXPIRED,
    # CONFIRMED
    (OrderStatus.CONFIRMED, OrderAction.ACTIVATE): OrderStatus.ACTIVE,
    (OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_USER): OrderStatus.CANCELED_BY_USER,
    (OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_ORG): OrderStatus.CANCELED_BY_ORGANIZATION,
    # ACTIVE
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
