from datetime import UTC, datetime, timedelta

from app.core.enums import OrderStatus

_TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.FINISHED,
        OrderStatus.REJECTED,
        OrderStatus.DECLINED,
        OrderStatus.CANCELED_BY_USER,
        OrderStatus.CANCELED_BY_ORGANIZATION,
    }
)


def get_chat_status(
    *,
    order_status: OrderStatus,
    order_updated_at: datetime,
    last_message_at: datetime | None,
    cooldown_days: int,
    now: datetime | None = None,
) -> str:
    """Return 'active' or 'read_only' based on order status and cooldown."""
    if order_status not in _TERMINAL_STATUSES:
        return "active"

    if now is None:
        now = datetime.now(tz=UTC)

    reference = last_message_at if last_message_at is not None else order_updated_at
    deadline = reference + timedelta(days=cooldown_days)
    if now < deadline:
        return "active"
    return "read_only"
