from app.chat.models import ChatMessage
from app.core.enums import ChatMessageType, ChatSide, NotificationType, OrderStatus


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
    return messages
