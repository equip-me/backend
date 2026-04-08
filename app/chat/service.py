import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from tortoise.expressions import Q

from app.chat.models import ChatMessage
from app.chat.schemas import ChatStatusResponse, MediaAttachmentRead, MessageRead
from app.core.config import get_settings
from app.core.enums import ChatMessageType, MediaOwnerType, MediaStatus, OrderStatus
from app.core.exceptions import AppValidationError, NotFoundError, PermissionDeniedError
from app.core.pagination import CursorParams, PaginatedResponse, paginate
from app.media.models import Media
from app.media.storage import StorageClient, get_storage
from app.orders.models import Order
from app.users.models import User

_TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.FINISHED,
        OrderStatus.CANCELED_BY_USER,
        OrderStatus.CANCELED_BY_ORGANIZATION,
        OrderStatus.EXPIRED,
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


def _get_side(user: User, order: Order) -> str:
    return "requester" if user.id == order.requester_id else "organization"


async def _get_author_name(user: User, order: Order) -> str:
    if user.id == order.requester_id:
        return f"{user.name} {user.surname}"
    await order.fetch_related("organization")
    return str(order.organization.short_name)


async def _resolve_media_urls(
    snapshots: list[dict[str, Any]],
    storage: StorageClient,
) -> list[MediaAttachmentRead]:
    settings = get_settings()
    expires = settings.storage.presigned_url_expiry_seconds
    result: list[MediaAttachmentRead] = []
    for snap in snapshots:
        urls: dict[str, str] = {}
        for variant_name, s3_key in snap.get("variants", {}).items():
            urls[variant_name] = await storage.generate_download_url(s3_key, expires)
        result.append(
            MediaAttachmentRead(
                id=snap["id"],
                kind=snap["kind"],
                urls=urls,
                original_filename=snap["original_filename"],
                content_type=snap["content_type"],
            )
        )
    return result


async def _to_message_read(
    msg: ChatMessage,
    order: Order,
    storage: StorageClient,
) -> MessageRead:
    if msg.message_type == ChatMessageType.NOTIFICATION:
        return MessageRead(
            id=msg.id,
            side=msg.recipient_side.value if msg.recipient_side else "requester",
            name=None,
            text=None,
            media=[],
            message_type=msg.message_type,
            notification_type=msg.notification_type,
            notification_body=msg.notification_body,
            created_at=msg.created_at,
            read_at=msg.read_at,
        )
    sender: User = msg.sender
    side = _get_side(sender, order)
    name = await _get_author_name(sender, order)
    media = await _resolve_media_urls(msg.media, storage)
    return MessageRead(
        id=msg.id,
        side=side,
        name=name,
        text=msg.text,
        media=media,
        message_type=msg.message_type,
        notification_type=None,
        notification_body=None,
        created_at=msg.created_at,
        read_at=msg.read_at,
    )


async def compute_chat_status_for_order(order: Order, user: User) -> ChatStatusResponse:
    settings = get_settings()
    side = _get_side(user, order)
    last_msg = (
        await ChatMessage.filter(Q(order_id=order.id) & (Q(recipient_side__isnull=True) | Q(recipient_side=side)))
        .order_by("-created_at")
        .first()
    )
    last_message_at = last_msg.created_at if last_msg else None
    status = get_chat_status(
        order_status=OrderStatus(order.status),
        order_updated_at=order.updated_at,
        last_message_at=last_message_at,
        cooldown_days=settings.chat.cooldown_days,
    )
    unread_count = await ChatMessage.filter(
        Q(order_id=order.id)
        & (Q(recipient_side__isnull=True) | Q(recipient_side=side))
        & (Q(sender_id__isnull=True) | ~Q(sender_id=user.id)),
        read_at=None,
    ).count()
    return ChatStatusResponse(status=status, unread_count=unread_count)


async def send_message(
    order: Order,
    user: User,
    text: str | None,
    media_ids: list[str],
) -> MessageRead:
    settings = get_settings()

    if not text and not media_ids:
        raise AppValidationError("Message must have text or attachments", code="chat.message_empty")
    if text and len(text) > settings.chat.max_message_length:
        raise AppValidationError(
            f"Message exceeds maximum length of {settings.chat.max_message_length}",
            code="chat.message_too_long",
            params={"max_length": settings.chat.max_message_length},
        )
    if len(media_ids) > settings.chat.max_attachments_per_message:
        raise AppValidationError(
            f"Maximum {settings.chat.max_attachments_per_message} attachments per message",
            code="chat.too_many_attachments",
            params={"max": settings.chat.max_attachments_per_message},
        )

    # Validate and snapshot media
    media_snapshots: list[dict[str, Any]] = []
    media_records: list[Media] = []
    for mid_str in media_ids:
        try:
            mid = UUID(mid_str)
        except ValueError as e:
            raise AppValidationError(
                f"Invalid media ID: {mid_str}",
                code="chat.invalid_media_id",
                params={"id": mid_str},
            ) from e
        media = await Media.get_or_none(id=mid).prefetch_related("uploaded_by")
        if media is None:
            raise NotFoundError(
                f"Media {mid_str} not found",
                code="chat.media_not_found",
                params={"id": mid_str},
            )
        if media.status != MediaStatus.READY:
            raise AppValidationError(
                f"Media {mid_str} is not ready",
                code="chat.media_not_ready",
                params={"id": mid_str},
            )
        uploader: User = media.uploaded_by
        if uploader.id != user.id:
            raise PermissionDeniedError(
                f"Media {mid_str} was not uploaded by you",
                code="chat.media_not_yours",
                params={"id": mid_str},
            )
        media_snapshots.append(
            {
                "id": str(media.id),
                "kind": media.kind.value,
                "variants": media.variants,
                "original_filename": media.original_filename,
                "content_type": media.content_type,
            }
        )
        media_records.append(media)

    msg = await ChatMessage.create(
        order=order,
        sender=user,
        text=text,
        media=media_snapshots,
    )

    # Link media records to message for S3 lifecycle
    for media in media_records:
        media.owner_type = MediaOwnerType.MESSAGE
        media.owner_id = str(msg.id)
        await media.save()

    # Reload with sender for author resolution
    await msg.fetch_related("sender")
    storage = get_storage()
    return await _to_message_read(msg, order, storage)


async def get_messages(
    order: Order,
    params: CursorParams,
    *,
    side: str,
) -> PaginatedResponse[MessageRead]:
    qs = ChatMessage.filter(
        Q(order_id=order.id) & (Q(recipient_side__isnull=True) | Q(recipient_side=side))
    ).prefetch_related("sender")
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-created_at", "-id"))

    storage = get_storage()
    reads: list[MessageRead] = await asyncio.gather(*[_to_message_read(msg, order, storage) for msg in items])

    return PaginatedResponse(items=reads, next_cursor=next_cursor, has_more=has_more)


async def mark_messages_read(order_id: str, user_id: str, until_message_id: str, *, side: str) -> int:
    until_msg = await ChatMessage.get_or_none(id=until_message_id, order_id=order_id)
    if until_msg is None:
        raise NotFoundError("Message not found", code="chat.message_not_found")

    count: int = await ChatMessage.filter(
        Q(order_id=order_id)
        & (Q(recipient_side__isnull=True) | Q(recipient_side=side))
        & (Q(sender_id__isnull=True) | ~Q(sender_id=user_id)),
        read_at=None,
        created_at__lte=until_msg.created_at,
    ).update(read_at=datetime.now(tz=UTC))

    return count
