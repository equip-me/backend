import logging
from typing import Any

logger = logging.getLogger(__name__)


async def notify_new_chat_message(_ctx: dict[Any, Any], order_id: str, message_id: str) -> None:
    """Stub for chat message notifications. Hook point for future push notifications."""
    logger.info("Chat notification: order=%s message=%s (stub — no notification sent)", order_id, message_id)
