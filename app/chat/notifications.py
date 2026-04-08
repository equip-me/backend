import logging

from app.chat.models import ChatMessage
from app.core.enums import ChatMessageType, ChatSide, NotificationType, OrderStatus

logger = logging.getLogger(__name__)


async def create_status_notification(
    *,
    order_id: str,
    old_status: OrderStatus,
    new_status: OrderStatus,
) -> list[ChatMessage]:
    """Create two notification messages (one per side) for an order status change."""
    body = {"old_status": old_status.value, "new_status": new_status.value}
    messages: list[ChatMessage] = []
    for side in (ChatSide.REQUESTER, ChatSide.ORGANIZATION):
        msg = await ChatMessage.create(
            order_id=order_id,
            sender=None,
            message_type=ChatMessageType.NOTIFICATION,
            notification_type=NotificationType.STATUS_CHANGED,
            recipient_side=side,
            notification_body=body,
            text=None,
            media=[],
        )
        messages.append(msg)

    # Broadcast to connected WebSocket clients
    try:
        from app.chat.pubsub import publish

        for msg in messages:
            payload = {
                "type": "notification",
                "data": {
                    "id": str(msg.id),
                    "message_type": msg.message_type.value,
                    "notification_type": msg.notification_type.value if msg.notification_type else None,
                    "notification_body": msg.notification_body,
                    "created_at": msg.created_at.isoformat(),
                    "read_at": None,
                },
                "_recipient_side": msg.recipient_side.value if msg.recipient_side else None,
            }
            await publish(f"chat:{order_id}", payload)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to broadcast notification for order %s", order_id, exc_info=True)

    return messages
