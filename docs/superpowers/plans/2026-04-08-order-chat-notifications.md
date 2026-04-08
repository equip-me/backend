# Order Chat Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add system-generated notification messages to order chat when order status changes, with per-side read tracking.

**Architecture:** Add `message_type`, `notification_type`, `recipient_side`, `notification_body` fields to `ChatMessage`. On each status transition, create two notification rows (one per side). Update all query/read/unread logic with side-aware filtering. Update WebSocket connection registry to store side for targeted broadcast.

**Tech Stack:** Python 3.14, FastAPI, Tortoise ORM, Pydantic v2, Redis pub/sub, pytest + httpx

**Spec:** `docs/superpowers/specs/2026-04-08-order-chat-notifications-design.md`

---

### Task 1: Add New Enums

**Files:**
- Modify: `app/core/enums.py:82` (append after MediaStatus)

- [ ] **Step 1: Write failing test for new enums**

Create `tests/unit/test_chat_notification_enums.py`:

```python
from app.core.enums import ChatMessageType, ChatSide, NotificationType


class TestChatNotificationEnums:
    def test_chat_message_type_values(self) -> None:
        assert ChatMessageType.USER == "user"
        assert ChatMessageType.NOTIFICATION == "notification"

    def test_notification_type_values(self) -> None:
        assert NotificationType.STATUS_CHANGED == "status_changed"

    def test_chat_side_values(self) -> None:
        assert ChatSide.REQUESTER == "requester"
        assert ChatSide.ORGANIZATION == "organization"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_chat_notification_enums.py -v`
Expected: `ImportError: cannot import name 'ChatMessageType'`

- [ ] **Step 3: Add enums to `app/core/enums.py`**

Append after `MediaStatus` (after line 81):

```python
class ChatMessageType(StrEnum):
    USER = "user"
    NOTIFICATION = "notification"


class NotificationType(StrEnum):
    STATUS_CHANGED = "status_changed"


class ChatSide(StrEnum):
    REQUESTER = "requester"
    ORGANIZATION = "organization"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_chat_notification_enums.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Run linting**

Run: `task ruff:fix && task mypy`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add app/core/enums.py tests/unit/test_chat_notification_enums.py
git commit -m "feat(chat): add ChatMessageType, NotificationType, ChatSide enums"
```

---

### Task 2: Update ChatMessage Model + Migration

**Files:**
- Modify: `app/chat/models.py:8-21`
- Test: `tests/db/test_chat_message.py`

- [ ] **Step 1: Write failing test for notification message creation**

Add to `tests/db/test_chat_message.py`, new test in `TestChatMessageCRUD`:

```python
async def test_create_notification_message(self) -> None:
    user = await _create_user()
    order = await _create_order(user)
    msg = await ChatMessage.create(
        order=order,
        sender=None,
        message_type=ChatMessageType.NOTIFICATION,
        notification_type=NotificationType.STATUS_CHANGED,
        recipient_side=ChatSide.REQUESTER,
        notification_body={"old_status": "pending", "new_status": "offered"},
        text=None,
        media=[],
    )
    assert msg.sender_id is None
    assert msg.message_type == ChatMessageType.NOTIFICATION
    assert msg.notification_type == NotificationType.STATUS_CHANGED
    assert msg.recipient_side == ChatSide.REQUESTER
    assert msg.notification_body == {"old_status": "pending", "new_status": "offered"}
    assert msg.text is None
```

Add the imports at the top of the file:

```python
from app.core.enums import ChatMessageType, ChatSide, NotificationType
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_chat_message.py::TestChatMessageCRUD::test_create_notification_message -v`
Expected: FAIL — `ChatMessage` has no `message_type` field

- [ ] **Step 3: Update ChatMessage model**

Replace the full `ChatMessage` class in `app/chat/models.py`:

```python
from typing import Any, ClassVar
from uuid import uuid4

from tortoise import fields
from tortoise.models import Model

from app.core.enums import ChatMessageType, ChatSide, NotificationType


class ChatMessage(Model):
    id = fields.UUIDField(primary_key=True, default=uuid4)
    order: Any = fields.ForeignKeyField("models.Order", related_name="messages")
    order_id: str
    sender: Any = fields.ForeignKeyField("models.User", related_name="sent_messages", null=True)
    sender_id: str | None
    text = fields.TextField(null=True)
    media: Any = fields.JSONField(default=list)
    message_type = fields.CharEnumField(ChatMessageType, default=ChatMessageType.USER, max_length=20)
    notification_type = fields.CharEnumField(NotificationType, null=True, max_length=20)
    recipient_side = fields.CharEnumField(ChatSide, null=True, max_length=20)
    notification_body: Any = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    read_at = fields.DatetimeField(null=True)

    class Meta:
        table = "chat_messages"
        ordering: ClassVar[list[str]] = ["-created_at"]
```

- [ ] **Step 4: Generate and apply migration**

Run: `task db:makemigrations` (or regenerate schemas in test). Since tests use `generate_schemas()`, the new columns will be created automatically in the test DB.

For production, create a migration file. The migration must:
1. Add `message_type VARCHAR(20) NOT NULL DEFAULT 'user'`
2. Add `notification_type VARCHAR(20) NULL`
3. Add `recipient_side VARCHAR(20) NULL`
4. Add `notification_body JSONB NULL`
5. Alter `sender_id` to be nullable: `ALTER TABLE chat_messages ALTER COLUMN sender_id DROP NOT NULL`

Run: `task db:makemigrations`

- [ ] **Step 5: Run the test**

Run: `pytest tests/db/test_chat_message.py::TestChatMessageCRUD::test_create_notification_message -v`
Expected: PASS

- [ ] **Step 6: Run all existing chat model tests to verify no regressions**

Run: `pytest tests/db/test_chat_message.py -v`
Expected: all 5 tests PASS (existing 4 + new 1)

- [ ] **Step 7: Run linting**

Run: `task ruff:fix && task mypy`
Expected: clean

- [ ] **Step 8: Commit**

```bash
git add app/chat/models.py tests/db/test_chat_message.py
git commit -m "feat(chat): add notification fields to ChatMessage model"
```

Also commit any generated migration file if present.

---

### Task 3: Update MessageRead Schema

**Files:**
- Modify: `app/chat/schemas.py:15-22`

- [ ] **Step 1: Write failing test for schema serialization**

Create `tests/unit/test_chat_notification_schema.py`:

```python
from datetime import UTC, datetime
from uuid import uuid4

from app.chat.schemas import MessageRead
from app.core.enums import ChatMessageType, NotificationType


class TestMessageReadSchema:
    def test_user_message_schema(self) -> None:
        msg = MessageRead(
            id=uuid4(),
            side="requester",
            name="Иван Иванов",
            text="Hello",
            media=[],
            message_type=ChatMessageType.USER,
            notification_type=None,
            notification_body=None,
            created_at=datetime.now(tz=UTC),
            read_at=None,
        )
        assert msg.message_type == "user"
        assert msg.name == "Иван Иванов"

    def test_notification_message_schema(self) -> None:
        msg = MessageRead(
            id=uuid4(),
            side="requester",
            name=None,
            text=None,
            media=[],
            message_type=ChatMessageType.NOTIFICATION,
            notification_type=NotificationType.STATUS_CHANGED,
            notification_body={"old_status": "pending", "new_status": "offered"},
            created_at=datetime.now(tz=UTC),
            read_at=None,
        )
        assert msg.message_type == "notification"
        assert msg.notification_type == "status_changed"
        assert msg.notification_body == {"old_status": "pending", "new_status": "offered"}
        assert msg.name is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_chat_notification_schema.py -v`
Expected: FAIL — `MessageRead` doesn't accept `message_type` field

- [ ] **Step 3: Update MessageRead schema**

Replace `MessageRead` in `app/chat/schemas.py`:

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.core.enums import ChatMessageType, NotificationType


class MediaAttachmentRead(BaseModel):
    id: str
    kind: str
    urls: dict[str, str]
    original_filename: str
    content_type: str


class MessageRead(BaseModel):
    id: UUID
    side: str
    name: str | None
    text: str | None
    media: list[MediaAttachmentRead]
    message_type: ChatMessageType
    notification_type: NotificationType | None
    notification_body: dict[str, str] | None
    created_at: datetime
    read_at: datetime | None


class ChatStatusResponse(BaseModel):
    status: str
    unread_count: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_chat_notification_schema.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Run linting**

Run: `task ruff:fix && task mypy`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add app/chat/schemas.py tests/unit/test_chat_notification_schema.py
git commit -m "feat(chat): add notification fields to MessageRead schema"
```

---

### Task 4: Update `_to_message_read` + Chat Service for Side-Aware Filtering

**Files:**
- Modify: `app/chat/service.py:49-50` (`_get_side`), `83-100` (`_to_message_read`), `103-121` (`compute_chat_status_for_order`), `209-219` (`get_messages`), `222-237` (`mark_messages_read`)
- Modify: `app/chat/router.py:18-62` (pass side to service functions)
- Modify: `app/chat/websocket.py:101-111` (`_listen_redis`), `212-229` (read handler), `254` (compute_chat_status)

This task updates all the chat service functions to handle notification messages and side-aware filtering.

- [ ] **Step 1: Write failing DB test for side-aware `get_messages`**

Add to `tests/db/test_chat_message.py`:

```python
async def test_get_messages_filters_by_side(self) -> None:
    """Notification messages are only visible to their recipient side."""
    user = await _create_user()
    order = await _create_order(user)

    # Regular message (visible to both)
    await ChatMessage.create(order=order, sender=user, text="Hello", media=[])

    # Notification for requester only
    await ChatMessage.create(
        order=order,
        sender=None,
        message_type=ChatMessageType.NOTIFICATION,
        notification_type=NotificationType.STATUS_CHANGED,
        recipient_side=ChatSide.REQUESTER,
        notification_body={"old_status": "pending", "new_status": "offered"},
        text=None,
        media=[],
    )

    # Notification for organization only
    await ChatMessage.create(
        order=order,
        sender=None,
        message_type=ChatMessageType.NOTIFICATION,
        notification_type=NotificationType.STATUS_CHANGED,
        recipient_side=ChatSide.ORGANIZATION,
        notification_body={"old_status": "pending", "new_status": "offered"},
        text=None,
        media=[],
    )

    from tortoise.queryset import Q

    # Requester sees regular + their notification = 2
    requester_msgs = await ChatMessage.filter(
        Q(order_id=order.id) & (Q(recipient_side__isnull=True) | Q(recipient_side=ChatSide.REQUESTER))
    )
    assert len(requester_msgs) == 2

    # Organization sees regular + their notification = 2
    org_msgs = await ChatMessage.filter(
        Q(order_id=order.id) & (Q(recipient_side__isnull=True) | Q(recipient_side=ChatSide.ORGANIZATION))
    )
    assert len(org_msgs) == 2
```

- [ ] **Step 2: Run test to verify it passes (raw query test — model already supports fields)**

Run: `pytest tests/db/test_chat_message.py::TestChatMessageCRUD::test_get_messages_filters_by_side -v`
Expected: PASS (this tests raw Tortoise queries — model already has the fields from Task 2)

- [ ] **Step 3: Update `_to_message_read` to handle notification messages**

In `app/chat/service.py`, replace `_to_message_read` (lines 83-100):

```python
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
```

Add `ChatMessageType` to the imports at the top of `app/chat/service.py`:

```python
from app.core.enums import ChatMessageType, MediaOwnerType, MediaStatus, OrderStatus
```

- [ ] **Step 4: Update `get_messages` to accept `side` parameter and filter**

In `app/chat/service.py`, replace `get_messages` (lines 209-219):

```python
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
```

Add `Q` to the Tortoise imports:

```python
from tortoise.queryset import Q
```

- [ ] **Step 5: Update `compute_chat_status_for_order` for side-aware unread count**

In `app/chat/service.py`, replace `compute_chat_status_for_order` (lines 103-121):

```python
async def compute_chat_status_for_order(order: Order, user: User) -> ChatStatusResponse:
    settings = get_settings()
    side = _get_side(user, order)
    last_msg = await ChatMessage.filter(
        Q(order_id=order.id) & (Q(recipient_side__isnull=True) | Q(recipient_side=side))
    ).order_by("-created_at").first()
    last_message_at = last_msg.created_at if last_msg else None
    status = get_chat_status(
        order_status=OrderStatus(order.status),
        order_updated_at=order.updated_at,
        last_message_at=last_message_at,
        cooldown_days=settings.chat.cooldown_days,
    )
    unread_count = (
        await ChatMessage.filter(
            Q(order_id=order.id) & (Q(recipient_side__isnull=True) | Q(recipient_side=side)),
            read_at=None,
        )
        .exclude(sender_id=user.id)
        .count()
    )
    return ChatStatusResponse(status=status, unread_count=unread_count)
```

- [ ] **Step 6: Update `mark_messages_read` for side-aware filtering**

In `app/chat/service.py`, replace `mark_messages_read` (lines 222-237):

```python
async def mark_messages_read(order_id: str, user_id: str, until_message_id: str, *, side: str) -> int:
    until_msg = await ChatMessage.get_or_none(id=until_message_id, order_id=order_id)
    if until_msg is None:
        raise NotFoundError("Message not found", code="chat.message_not_found")

    count: int = (
        await ChatMessage.filter(
            Q(order_id=order_id) & (Q(recipient_side__isnull=True) | Q(recipient_side=side)),
            read_at=None,
            created_at__lte=until_msg.created_at,
        )
        .exclude(sender_id=user_id)
        .update(read_at=datetime.now(tz=UTC))
    )

    return count
```

- [ ] **Step 7: Update router to pass `side` to `get_messages`**

In `app/chat/router.py`, update all four endpoints:

```python
from typing import Annotated

from fastapi import APIRouter, Depends

from app.chat import service
from app.chat.dependencies import require_chat_participant_org, require_chat_participant_user
from app.chat.schemas import ChatStatusResponse, MessageRead
from app.core.pagination import CursorParams, PaginatedResponse
from app.orders.models import Order
from app.users.models import User

router = APIRouter(prefix="/api/v1", tags=["Chat"])


# --- User (renter) endpoints ---


@router.get("/orders/{order_id}/chat/messages", response_model=PaginatedResponse[MessageRead])
async def get_user_chat_messages(
    participant: Annotated[tuple[Order, User], Depends(require_chat_participant_user)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[MessageRead]:
    order, _user = participant
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.get_messages(order, params, side="requester")


@router.get("/orders/{order_id}/chat/status", response_model=ChatStatusResponse)
async def get_user_chat_status(
    participant: Annotated[tuple[Order, User], Depends(require_chat_participant_user)],
) -> ChatStatusResponse:
    order, user = participant
    return await service.compute_chat_status_for_order(order, user)


# --- Organization endpoints ---


@router.get(
    "/organizations/{org_id}/orders/{order_id}/chat/messages",
    response_model=PaginatedResponse[MessageRead],
)
async def get_org_chat_messages(
    participant: Annotated[tuple[Order, User], Depends(require_chat_participant_org)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[MessageRead]:
    order, _user = participant
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.get_messages(order, params, side="organization")


@router.get(
    "/organizations/{org_id}/orders/{order_id}/chat/status",
    response_model=ChatStatusResponse,
)
async def get_org_chat_status(
    participant: Annotated[tuple[Order, User], Depends(require_chat_participant_org)],
) -> ChatStatusResponse:
    order, user = participant
    return await service.compute_chat_status_for_order(order, user)
```

- [ ] **Step 8: Update WebSocket `_listen_client` to pass `side` to `mark_messages_read`**

In `app/chat/websocket.py`, update the read handler (around line 217):

Change:
```python
await service.mark_messages_read(order.id, user.id, until_id)
```
To:
```python
side = _get_side(user, order)
await service.mark_messages_read(order.id, user.id, until_id, side=side)
```

Note: `_get_side` is already defined in `websocket.py` at line 94.

- [ ] **Step 9: Run all existing tests**

Run: `pytest tests/ -v`
Expected: all tests PASS. The existing tests create `ChatMessage` without `message_type` — defaults to `"user"`, and `recipient_side` defaults to `None` so the filter `recipient_side__isnull=True` matches them.

- [ ] **Step 10: Run linting**

Run: `task ruff:fix && task mypy`
Expected: clean

- [ ] **Step 11: Commit**

```bash
git add app/chat/service.py app/chat/router.py app/chat/websocket.py tests/db/test_chat_message.py
git commit -m "feat(chat): add side-aware filtering for messages, unread count, and read tracking"
```

---

### Task 5: Create Notification Service + Hook Into Order Transitions

**Files:**
- Create: `app/chat/notifications.py`
- Modify: `app/orders/service.py:23-25` (`_record_transition`)
- Modify: `app/worker/orders.py` (add `_record_transition` calls)

- [ ] **Step 1: Write failing DB test for notification creation**

Create `tests/db/test_chat_notifications.py`:

```python
from typing import Any

import pytest

from app.chat.models import ChatMessage
from app.chat.notifications import create_status_notification
from app.core.enums import ChatMessageType, ChatSide, NotificationType, OrderStatus
from app.orders.models import Order
from app.users.models import User


async def _create_user(email: str = "user@test.com") -> User:
    return await User.create(
        email=email,
        password_hash="x",
        phone="+79991234567",
        name="Иван",
        surname="Иванов",
    )


async def _create_order(requester: User) -> Order:
    from app.listings.models import Listing, ListingCategory

    cat = await ListingCategory.create(name="Test", verified=True)
    org = await _create_org()
    listing = await Listing.create(
        name="Test Listing",
        category=cat,
        organization=org,
        price=1000,
        status="published",
    )
    return await Order.create(
        id="TSTORD",
        listing=listing,
        organization=org,
        requester=requester,
        requested_start_date="2026-04-10",
        requested_end_date="2026-04-15",
        estimated_cost=5000,
    )


async def _create_org() -> Any:
    from app.organizations.models import Organization

    return await Organization.create(
        full_name="Test Org LLC",
        short_name="TestOrg",
        inn="7707083893",
        status="verified",
    )


class TestCreateStatusNotification:
    async def test_creates_two_messages(self) -> None:
        user = await _create_user()
        order = await _create_order(user)
        msgs = await create_status_notification(
            order_id=order.id,
            old_status=OrderStatus.PENDING,
            new_status=OrderStatus.OFFERED,
        )
        assert len(msgs) == 2

    async def test_one_per_side(self) -> None:
        user = await _create_user()
        order = await _create_order(user)
        msgs = await create_status_notification(
            order_id=order.id,
            old_status=OrderStatus.PENDING,
            new_status=OrderStatus.OFFERED,
        )
        sides = {m.recipient_side for m in msgs}
        assert sides == {ChatSide.REQUESTER, ChatSide.ORGANIZATION}

    async def test_notification_fields(self) -> None:
        user = await _create_user()
        order = await _create_order(user)
        msgs = await create_status_notification(
            order_id=order.id,
            old_status=OrderStatus.OFFERED,
            new_status=OrderStatus.ACCEPTED,
        )
        for msg in msgs:
            assert msg.message_type == ChatMessageType.NOTIFICATION
            assert msg.notification_type == NotificationType.STATUS_CHANGED
            assert msg.notification_body == {"old_status": "offered", "new_status": "accepted"}
            assert msg.sender_id is None
            assert msg.text is None
            assert msg.media == []

    async def test_messages_persisted_in_db(self) -> None:
        user = await _create_user()
        order = await _create_order(user)
        await create_status_notification(
            order_id=order.id,
            old_status=OrderStatus.PENDING,
            new_status=OrderStatus.OFFERED,
        )
        count = await ChatMessage.filter(
            order_id=order.id,
            message_type=ChatMessageType.NOTIFICATION,
        ).count()
        assert count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_chat_notifications.py -v`
Expected: `ImportError: cannot import name 'create_status_notification' from 'app.chat.notifications'`

- [ ] **Step 3: Create `app/chat/notifications.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/db/test_chat_notifications.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Run linting**

Run: `task ruff:fix && task mypy`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add app/chat/notifications.py tests/db/test_chat_notifications.py
git commit -m "feat(chat): add create_status_notification function"
```

---

### Task 6: Hook Notifications Into Order Transitions (Service Layer)

**Files:**
- Modify: `app/orders/service.py:23-25` (`_record_transition`)

- [ ] **Step 1: Write integration test for notifications on offer**

Add to `tests/db/test_chat_notifications.py`:

```python
class TestNotificationsOnTransition:
    """Verify that order transitions create notification messages."""

    async def test_offer_creates_notifications(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Offering an order creates two notification messages."""
        order_id, _org_id, _org_token, _renter_token = create_order_for_chat
        # create_order_for_chat already creates a PENDING order then offers it.
        # The offer transition (pending→offered) should have created notifications.
        notifications = await ChatMessage.filter(
            order_id=order_id,
            message_type=ChatMessageType.NOTIFICATION,
        )
        assert len(notifications) == 2
        sides = {n.recipient_side for n in notifications}
        assert sides == {ChatSide.REQUESTER, ChatSide.ORGANIZATION}
        for n in notifications:
            assert n.notification_body["new_status"] == "offered"
```

Add the import at the top:

```python
from httpx import AsyncClient
```

And add the fixture import (pytest will resolve `client` and `create_order_for_chat` from conftest).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_chat_notifications.py::TestNotificationsOnTransition -v`
Expected: FAIL — `len(notifications) == 0` because `_record_transition` doesn't create notifications yet

- [ ] **Step 3: Update `_record_transition` in `app/orders/service.py`**

Make `_record_transition` async and add notification creation. Replace lines 23-25:

```python
async def _record_transition(order_id: str, old_status: OrderStatus, new_status: OrderStatus) -> None:
    order_transitions.add(1, {"from_status": old_status.value, "to_status": new_status.value})
    emit_event("order.status_changed", order_id=order_id, old_status=old_status.value, new_status=new_status.value)
    from app.chat.notifications import create_status_notification

    await create_status_notification(order_id=order_id, old_status=old_status, new_status=new_status)
```

- [ ] **Step 4: Update all callers to `await _record_transition()`**

In `app/orders/service.py`, change every call from `_record_transition(...)` to `await _record_transition(...)`:

- Line 106: `await _record_transition(order.id, old_status, new_status)`
- Line 119: `await _record_transition(order.id, old_status, order.status)`
- Line 139: `await _record_transition(order.id, old_status, order.status)`
- Line 154: `await _record_transition(order.id, old_status, order.status)`

All callers are already `async def`, so adding `await` is safe.

- [ ] **Step 5: Run the test**

Run: `pytest tests/db/test_chat_notifications.py::TestNotificationsOnTransition -v`
Expected: PASS

- [ ] **Step 6: Run all order and chat tests**

Run: `pytest tests/db/test_orders.py tests/db/test_chat_message.py tests/db/test_chat_notifications.py tests/e2e/test_order_happy_path.py tests/e2e/test_order_cancellations.py -v`
Expected: all PASS

- [ ] **Step 7: Run linting**

Run: `task ruff:fix && task mypy`
Expected: clean

- [ ] **Step 8: Commit**

```bash
git add app/orders/service.py tests/db/test_chat_notifications.py
git commit -m "feat(chat): create notifications on order status transitions"
```

---

### Task 7: Hook Notifications Into Worker (Automated Transitions)

**Files:**
- Modify: `app/worker/orders.py:24-87` (expire_order, activate_order, finish_order)

The worker functions currently do NOT call `_record_transition`. They must call it so automated transitions also generate notifications.

- [ ] **Step 1: Write failing test for worker notification creation**

Add to `tests/db/test_order_worker.py`:

```python
class TestWorkerNotifications:
    async def test_expire_creates_notifications(self, pending_order: Order) -> None:
        await expire_order(_empty_ctx(), pending_order.id)
        from app.chat.models import ChatMessage
        from app.core.enums import ChatMessageType

        count = await ChatMessage.filter(
            order_id=pending_order.id,
            message_type=ChatMessageType.NOTIFICATION,
        ).count()
        assert count == 2

    async def test_activate_creates_notifications(self, pending_order: Order) -> None:
        from datetime import UTC, datetime

        # Advance to CONFIRMED
        from app.core.enums import OrderAction
        from app.orders.state_machine import transition

        pending_order.status = transition(pending_order.status, OrderAction.OFFER_BY_ORG)
        pending_order.offered_start_date = datetime.now(UTC).date()
        pending_order.offered_end_date = datetime.now(UTC).date()
        pending_order.offered_cost = 5000
        await pending_order.save()
        pending_order.status = transition(pending_order.status, OrderAction.ACCEPT_BY_USER)
        await pending_order.save()
        pending_order.status = transition(pending_order.status, OrderAction.APPROVE_BY_ORG)
        await pending_order.save()

        await activate_order(_empty_ctx(), pending_order.id)

        from app.chat.models import ChatMessage
        from app.core.enums import ChatMessageType

        notifs = await ChatMessage.filter(
            order_id=pending_order.id,
            message_type=ChatMessageType.NOTIFICATION,
        )
        # Should have notification for activate transition
        activate_notifs = [n for n in notifs if n.notification_body.get("new_status") == "active"]
        assert len(activate_notifs) == 2

    async def test_finish_creates_notifications(self, pending_order: Order) -> None:
        # Set to ACTIVE directly
        from app.core.enums import OrderStatus

        pending_order.status = OrderStatus.ACTIVE
        await pending_order.save()

        await finish_order(_empty_ctx(), pending_order.id)

        from app.chat.models import ChatMessage
        from app.core.enums import ChatMessageType

        notifs = await ChatMessage.filter(
            order_id=pending_order.id,
            message_type=ChatMessageType.NOTIFICATION,
        )
        finish_notifs = [n for n in notifs if n.notification_body.get("new_status") == "finished"]
        assert len(finish_notifs) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_order_worker.py::TestWorkerNotifications -v`
Expected: FAIL — `count == 0` (worker doesn't create notifications)

- [ ] **Step 3: Update worker functions to call `_record_transition`**

In `app/worker/orders.py`, add the import and update the three functions:

Add import:
```python
from app.orders.service import _record_transition
```

Update `expire_order` — replace the try block (lines 33-39):
```python
    try:
        old_status = order.status
        order.status = transition(order.status, OrderAction.EXPIRE)
        await order.save()
        await _record_transition(order.id, old_status, order.status)
        logger.info("Expired order %s: %s → %s", order_id, old_status.value, order.status.value)
    except AppValidationError:
        logger.warning("expire_order: cannot expire order %s in status %s", order_id, order.status.value)
```

Update `activate_order` — replace the try block (lines 51-68):
```python
    try:
        old_status = order.status
        order.status = transition(order.status, OrderAction.ACTIVATE)
        await order.save()
        await _record_transition(order.id, old_status, order.status)
        logger.info("Activated order %s: %s → %s", order_id, old_status.value, order.status.value)

        # Schedule finish job
        if order.offered_end_date is not None:
            from app.worker.settings import get_arq_pool

            pool = await get_arq_pool()
            from datetime import timedelta

            finish_at = datetime.combine(order.offered_end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            await pool.enqueue_job("finish_order", order.id, _defer_until=finish_at)

    except AppValidationError:
        logger.warning("activate_order: cannot activate order %s in status %s", order_id, order.status.value)
```

Update `finish_order` — replace the try block (lines 80-86):
```python
    try:
        old_status = order.status
        order.status = transition(order.status, OrderAction.FINISH)
        await order.save()
        await _record_transition(order.id, old_status, order.status)
        logger.info("Finished order %s: %s → %s", order_id, old_status.value, order.status.value)
    except AppValidationError:
        logger.warning("finish_order: cannot finish order %s in status %s", order_id, order.status.value)
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/db/test_order_worker.py::TestWorkerNotifications -v`
Expected: 3 PASSED

- [ ] **Step 5: Run all worker tests**

Run: `pytest tests/db/test_order_worker.py -v`
Expected: all PASS

- [ ] **Step 6: Run linting**

Run: `task ruff:fix && task mypy`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add app/worker/orders.py tests/db/test_order_worker.py
git commit -m "feat(chat): create notifications for automated order transitions in worker"
```

---

### Task 8: WebSocket — Store Side in Connection Registry + Filtered Broadcast

**Files:**
- Modify: `app/chat/websocket.py:49-64` (connection registry), `94-96` (`_get_side`), `101-111` (`_listen_redis`), `235-274` (endpoint)

- [ ] **Step 1: Update connection registry to store side**

In `app/chat/websocket.py`, update the registry type and helpers (lines 49-63):

```python
_connections: dict[str, set[tuple[str, str, WebSocket]]] = {}


def _add_connection(order_id: str, user_id: str, side: str, ws: WebSocket) -> None:
    if order_id not in _connections:
        _connections[order_id] = set()
    _connections[order_id].add((user_id, side, ws))


def _remove_connection(order_id: str, user_id: str, side: str, ws: WebSocket) -> None:
    conns = _connections.get(order_id)
    if conns:
        conns.discard((user_id, side, ws))
        if not conns:
            del _connections[order_id]
```

- [ ] **Step 2: Update `_listen_redis` to filter notifications by side**

Replace `_listen_redis` (lines 101-111):

```python
async def _listen_redis(pubsub: PubSub, ws: WebSocket, user_id: str, side: str) -> None:
    async for raw_message in pubsub.listen():
        if raw_message["type"] != "message":
            continue
        payload: dict[str, Any] = json.loads(raw_message["data"])
        sender_id = payload.pop("_sender_id", None)
        recipient_side = payload.pop("_recipient_side", None)
        msg_type = payload.get("type")
        # Don't echo typing/read back to the sender
        if msg_type in ("typing", "read") and sender_id == user_id:
            continue
        # Filter notifications by side
        if recipient_side is not None and recipient_side != side:
            continue
        await ws.send_json(payload)
```

- [ ] **Step 3: Update WebSocket endpoint to pass side**

In the `chat_websocket` function (lines 235-274), update the connection management and task creation:

After `await websocket.accept()` (line 251), add side resolution:

```python
    side = _get_side(user, order)
```

Update `_add_connection` call (line 258):
```python
    _add_connection(order_id, user.id, side, websocket)
```

Update `_listen_redis` task (line 264):
```python
            tg.create_task(_listen_redis(pubsub, websocket, user.id, side))
```

Update `_remove_connection` in finally (line 271):
```python
        _remove_connection(order_id, user.id, side, websocket)
```

- [ ] **Step 4: Run all existing WebSocket tests**

Run: `pytest tests/e2e/test_chat.py -v`
Expected: all PASS — existing tests don't send notifications, so the `_recipient_side` filtering has no effect on them.

- [ ] **Step 5: Run linting**

Run: `task ruff:fix && task mypy`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add app/chat/websocket.py
git commit -m "feat(chat): store side in WebSocket connection registry, filter notification broadcasts"
```

---

### Task 9: Broadcast Notifications via WebSocket on Transition

**Files:**
- Modify: `app/chat/notifications.py` (add broadcast)

- [ ] **Step 1: Update `create_status_notification` to broadcast via Redis**

In `app/chat/notifications.py`, add broadcast after creating messages:

```python
import json
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
```

- [ ] **Step 2: Run all existing tests to verify no regressions**

Run: `pytest tests/ -v`
Expected: all PASS. The broadcast will fail silently in test contexts where Redis is initialized (DB/e2e tests) or where `publish` throws (unit tests skip Redis init).

- [ ] **Step 3: Run linting**

Run: `task ruff:fix && task mypy`
Expected: clean

- [ ] **Step 4: Commit**

```bash
git add app/chat/notifications.py
git commit -m "feat(chat): broadcast notification messages via Redis pub/sub"
```

---

### Task 10: Integration Tests — Full Flow

**Files:**
- Create: `tests/e2e/test_chat_notifications.py`

- [ ] **Step 1: Write REST integration test — notifications visible in chat history**

Create `tests/e2e/test_chat_notifications.py`:

```python
import asyncio
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws._api import AsyncWebSocketSession

from app.main import app


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_ws_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _ws_receive(ws: AsyncWebSocketSession) -> dict[str, Any]:
    msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
    return msg


class TestChatNotificationsREST:
    async def test_requester_sees_own_notification(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, org_id, org_token, renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers=_auth(renter_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        notifications = [m for m in items if m["message_type"] == "notification"]
        assert len(notifications) >= 1
        n = notifications[0]
        assert n["notification_type"] == "status_changed"
        assert n["notification_body"]["new_status"] == "offered"
        assert n["name"] is None
        assert n["side"] == "requester"

    async def test_org_sees_own_notification(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, org_id, org_token, renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/messages",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        notifications = [m for m in items if m["message_type"] == "notification"]
        assert len(notifications) >= 1
        n = notifications[0]
        assert n["side"] == "organization"

    async def test_requester_does_not_see_org_notification(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, org_id, org_token, renter_token = create_order_for_chat
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers=_auth(renter_token),
        )
        items = resp.json()["items"]
        for m in items:
            if m["message_type"] == "notification":
                assert m["side"] != "organization"

    async def test_unread_count_includes_notifications(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, org_id, org_token, renter_token = create_order_for_chat
        # Renter should have unread notification from offer transition
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/status",
            headers=_auth(renter_token),
        )
        assert resp.status_code == 200
        assert resp.json()["unread_count"] >= 1


class TestChatNotificationsWebSocket:
    async def test_notification_delivered_to_correct_side(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """When org accepts order, both sides receive their notification via WebSocket."""
        order_id, org_id, org_token, renter_token = create_order_for_chat

        # First accept the order as renter
        resp = await client.patch(
            f"/api/v1/orders/{order_id}/accept",
            headers=_auth(renter_token),
        )
        assert resp.status_code == 200

        renter_notifications: list[dict[str, Any]] = []
        org_notifications: list[dict[str, Any]] = []
        both_connected = asyncio.Event()
        approve_done = asyncio.Event()

        async def renter_ws() -> None:
            async with await _make_ws_client() as wsc:
                async with aconnect_ws(
                    f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc
                ) as ws:
                    connected = await _ws_receive(ws)
                    assert connected["type"] == "connected"
                    both_connected.set()
                    await approve_done.wait()
                    try:
                        msg = await _ws_receive(ws)
                        if msg["type"] == "notification":
                            renter_notifications.append(msg)
                    except asyncio.TimeoutError:
                        pass

        async def org_ws() -> None:
            async with await _make_ws_client() as wsc:
                async with aconnect_ws(
                    f"/api/v1/orders/{order_id}/chat/ws?token={org_token}", wsc
                ) as ws:
                    connected = await _ws_receive(ws)
                    assert connected["type"] == "connected"
                    await both_connected.wait()
                    # Approve order (triggers notification)
                    resp = await client.patch(
                        f"/api/v1/organizations/{org_id}/orders/{order_id}/approve",
                        headers=_auth(org_token),
                    )
                    assert resp.status_code == 200
                    approve_done.set()
                    try:
                        msg = await _ws_receive(ws)
                        if msg["type"] == "notification":
                            org_notifications.append(msg)
                    except asyncio.TimeoutError:
                        pass

        await asyncio.gather(renter_ws(), org_ws())

        assert len(renter_notifications) == 1
        assert renter_notifications[0]["data"]["notification_body"]["new_status"] == "confirmed"
        assert len(org_notifications) == 1
        assert org_notifications[0]["data"]["notification_body"]["new_status"] == "confirmed"
```

- [ ] **Step 2: Write edge case tests**

Add to `tests/e2e/test_chat_notifications.py`:

```python
class TestChatNotificationEdgeCases:
    async def test_read_only_marks_own_side(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Mark-as-read for requester does not affect org's notification."""
        order_id, org_id, org_token, renter_token = create_order_for_chat

        # Get requester's notifications
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers=_auth(renter_token),
        )
        items = resp.json()["items"]
        notifications = [m for m in items if m["message_type"] == "notification"]
        assert len(notifications) >= 1

        # Mark as read via WebSocket (renter side)
        async with await _make_ws_client() as wsc:
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}", wsc
            ) as ws:
                await _ws_receive(ws)  # connected
                await ws.send_json({"type": "read", "until_message_id": notifications[0]["id"]})
                await asyncio.sleep(0.2)

        # Org notification should still be unread
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/status",
            headers=_auth(org_token),
        )
        assert resp.json()["unread_count"] >= 1

    async def test_cancel_creates_notification_in_active_chat(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        """Canceling an order creates notification, chat stays active during cooldown."""
        order_id, org_id, org_token, renter_token = create_order_for_chat

        # Cancel order by user
        resp = await client.patch(
            f"/api/v1/orders/{order_id}/cancel",
            headers=_auth(renter_token),
        )
        assert resp.status_code == 200

        # Chat should still be active (within cooldown)
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/status",
            headers=_auth(renter_token),
        )
        assert resp.json()["status"] == "active"

        # Notification for cancellation should exist
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers=_auth(renter_token),
        )
        items = resp.json()["items"]
        cancel_notifs = [
            m for m in items
            if m["message_type"] == "notification"
            and m["notification_body"]["new_status"] == "canceled_by_user"
        ]
        assert len(cancel_notifs) == 1
```

- [ ] **Step 3: Run the tests**

Run: `pytest tests/e2e/test_chat_notifications.py -v`
Expected: all PASS

- [ ] **Step 4: Run the full test suite**

Run: `pytest tests/ -v`
Expected: all PASS

- [ ] **Step 5: Run linting**

Run: `task ruff:fix && task mypy`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add tests/e2e/test_chat_notifications.py
git commit -m "test(chat): add integration tests for order notification messages"
```

---

### Task 11: Final Validation

- [ ] **Step 1: Run full CI suite**

Run: `task ci`
Expected: ruff + mypy + all tests PASS

- [ ] **Step 2: Review migration**

Check that the migration file correctly:
1. Adds `message_type VARCHAR(20) NOT NULL DEFAULT 'user'`
2. Adds `notification_type VARCHAR(20) NULL`
3. Adds `recipient_side VARCHAR(20) NULL`
4. Adds `notification_body JSONB NULL`
5. Alters `sender_id` to nullable

- [ ] **Step 3: Commit any remaining files**

```bash
git add -A
git status
# Commit if there are uncommitted migration files or fixes
```
