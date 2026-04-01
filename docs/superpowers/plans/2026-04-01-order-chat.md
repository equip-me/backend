# Order Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time WebSocket chat between renter and organization within an order, with media attachments, read receipts, typing indicators, and configurable post-terminal cooldown.

**Architecture:** New `app/chat/` module. ChatMessage model with denormalized media snapshots. Redis pub/sub for cross-worker WebSocket fan-out. Per-order WebSocket endpoint with JWT auth via query param. REST endpoints for message history and status. Chat liveness derived from order status + configurable cooldown.

**Tech Stack:** FastAPI WebSocket, Tortoise ORM, Redis pub/sub (`redis.asyncio`), existing S3/media pipeline, ARQ for notification stubs, `httpx-ws` for WebSocket testing.

**Spec:** `docs/superpowers/specs/2026-03-31-order-chat-design.md`

---

## Codebase Conventions (for subagents)

These rules are mandatory. Violating them will cause CI to fail.

- **No `# type: ignore`** — fix the type error or restructure
- **No `from __future__ import annotations`** — Pydantic v2 and Tortoise need runtime types
- **Strict mypy** — every function fully typed, no implicit `Any`
- **Ruff** — line length 119, `select = ["ALL"]` with specific ignores (see `pyproject.toml`)
- **All config in `pyproject.toml`** — ruff, mypy, pytest, coverage
- Async everywhere (Tortoise ORM is async-native)
- Pydantic v2 schemas for request/response
- `from_attributes=True` on read schemas
- Tortoise model FK fields typed as `Any` (e.g., `order: Any = fields.ForeignKeyField(...)`) with explicit `order_id: str` companion
- Run `task ruff:fix && task mypy` after each implementation step
- Run `task test` to verify no regressions

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `app/chat/__init__.py` | Empty module init |
| `app/chat/models.py` | `ChatMessage` Tortoise model |
| `app/chat/schemas.py` | Pydantic schemas: `MessageRead`, `ChatStatusResponse`, `MediaAttachmentRead` |
| `app/chat/service.py` | Business logic: send message, get messages, mark read, chat status, liveness |
| `app/chat/dependencies.py` | `require_chat_participant` for REST endpoints |
| `app/chat/router.py` | REST endpoints (user-side + org-side message history and status) |
| `app/chat/pubsub.py` | Redis pub/sub wrapper: init, publish, subscribe |
| `app/chat/websocket.py` | WebSocket handler, connection registry, rate limiter |
| `tests/unit/test_chat_liveness.py` | Unit tests for chat active/read-only logic |
| `tests/unit/test_chat_rate_limiter.py` | Unit tests for per-connection rate limiter |
| `tests/db/test_chat_message.py` | DB tests for ChatMessage CRUD |
| `tests/e2e/test_chat.py` | E2E tests for full chat flow (WebSocket + REST) |

### Modified files

| File | Change |
|------|--------|
| `app/core/enums.py` | Add `MediaOwnerType.MESSAGE`, `MediaContext.CHAT` |
| `app/core/config.py` | Add `ChatSettings` class, add `chat` field to `Settings` |
| `app/core/pagination.py` | Handle `UUID` in `encode_cursor` |
| `app/core/database.py` | Add `app.chat.models` to `MODELS` list |
| `app/media/models.py` | Change `owner_id` max_length from 6 to 36 (UUID support) |
| `app/media/worker.py` | Add `"chat": "chat"` to `_CONTEXT_TO_VARIANT_SET` |
| `app/main.py` | Register chat routers + WebSocket, init/close Redis in lifespan |
| `config/base.yaml` | Add `chat:` section, add `chat` variant sets to `media:` |
| `pyproject.toml` | Add `redis[hiredis]` dependency, add `httpx-ws` test dependency |
| `tests/conftest.py` | Add `chat_messages` to `_TEST_TABLES`, add chat fixtures |

---

## Task 1: Foundation — Enums, Config, Dependencies, Media model

**Files:**
- Modify: `app/core/enums.py:64-73`
- Modify: `app/core/config.py:72-90`
- Modify: `config/base.yaml`
- Modify: `app/media/models.py:14`
- Modify: `app/core/pagination.py:22-31`
- Modify: `pyproject.toml:9-29` and `pyproject.toml:31-38`

- [ ] **Step 1: Add new enum values**

In `app/core/enums.py`, add `MESSAGE` to `MediaOwnerType` and `CHAT` to `MediaContext`:

```python
class MediaOwnerType(StrEnum):
    USER = "user"
    ORGANIZATION = "organization"
    LISTING = "listing"
    MESSAGE = "message"


class MediaContext(StrEnum):
    USER_PROFILE = "user_profile"
    ORG_PROFILE = "org_profile"
    LISTING = "listing"
    CHAT = "chat"
```

- [ ] **Step 2: Add ChatSettings to config**

In `app/core/config.py`, add `ChatSettings` class after `WorkerSettings`:

```python
class ChatSettings(BaseModel):
    cooldown_days: int = 7
    max_message_length: int = 4000
    max_attachments_per_message: int = 10
    rate_limit_per_minute: int = 30
```

Add `chat` field to `Settings`:

```python
class Settings(BaseSettings):
    # ... existing fields ...
    worker: WorkerSettings = WorkerSettings()
    chat: ChatSettings = ChatSettings()
```

- [ ] **Step 3: Add chat config to base.yaml**

Append to `config/base.yaml`:

```yaml
chat:
  cooldown_days: 7
  max_message_length: 4000
  max_attachments_per_message: 10
  rate_limit_per_minute: 30
```

Add chat variant sets under the existing `media:` section:

```yaml
media:
  # ... existing entries ...
  photo_variant_sets:
    # ... existing profile and listing ...
    chat:
      - { name: "thumbnail", max_width: 100, quality: 75 }
      - { name: "large", max_width: 1200, quality: 85 }
  video_variant_sets:
    # ... existing listing ...
    chat:
      - { name: "original", max_height: 4320, video_bitrate: "2M", audio: true }
```

Note: `max_height: 4320` (8K) effectively preserves original size since the ffmpeg scale filter uses `min(max_height, ih)`.

- [ ] **Step 4: Update Media model owner_id max_length**

In `app/media/models.py`, change `owner_id` max_length from 6 to 36 to support UUID references:

```python
owner_id = fields.CharField(max_length=36, null=True)
```

- [ ] **Step 5: Handle UUID in pagination cursor encoding**

In `app/core/pagination.py`, add UUID import and handling in `encode_cursor`:

```python
import json
from base64 import b64decode, b64encode
from datetime import datetime
from typing import Any
from uuid import UUID

# ... rest of imports ...

def encode_cursor(values: dict[str, Any]) -> str:
    """Encode cursor values as a base64 JSON string."""
    serialized: dict[str, Any] = {}
    for key, val in values.items():
        if isinstance(val, datetime):
            serialized[key] = val.isoformat()
        elif isinstance(val, UUID):
            serialized[key] = str(val)
        else:
            serialized[key] = val
    return b64encode(json.dumps(serialized).encode()).decode()
```

- [ ] **Step 6: Add dependencies to pyproject.toml**

Add `redis` to main dependencies in `pyproject.toml`:

```toml
[tool.poetry.dependencies]
# ... existing ...
redis = {version = ">=5.0.0", extras = ["hiredis"]}
```

Add `httpx-ws` to dev dependencies:

```toml
[tool.poetry.group.dev.dependencies]
# ... existing ...
httpx-ws = "*"
```

Add mypy override for redis:

```toml
[[tool.mypy.overrides]]
module = ["redis.*", "hiredis.*"]
ignore_missing_imports = true
```

- [ ] **Step 7: Install dependencies**

Run: `poetry lock --no-update && poetry install`

- [ ] **Step 8: Run lint and typecheck**

Run: `task ruff:fix && task mypy`

Expected: PASS (no errors)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(chat): add foundation — enums, config, media model update, pagination UUID support"
```

---

## Task 2: ChatMessage Model + DB Tests

**Files:**
- Create: `app/chat/__init__.py`
- Create: `app/chat/models.py`
- Modify: `app/core/database.py:3-9`
- Modify: `tests/conftest.py:18-28`
- Create: `tests/db/test_chat_message.py`

- [ ] **Step 1: Create chat module and model**

Create `app/chat/__init__.py` (empty file).

Create `app/chat/models.py`:

```python
from typing import Any, ClassVar
from uuid import uuid4

from tortoise import fields
from tortoise.models import Model


class ChatMessage(Model):
    id = fields.UUIDField(primary_key=True, default=uuid4)
    order: Any = fields.ForeignKeyField("models.Order", related_name="messages")
    order_id: str
    sender: Any = fields.ForeignKeyField("models.User", related_name="sent_messages")
    sender_id: str
    text = fields.TextField(null=True)
    media: Any = fields.JSONField(default=list)
    created_at = fields.DatetimeField(auto_now_add=True)
    read_at = fields.DatetimeField(null=True)

    class Meta:
        table = "chat_messages"
        ordering: ClassVar[list[str]] = ["-created_at"]
```

- [ ] **Step 2: Register model in database.py**

In `app/core/database.py`, add to the `MODELS` list:

```python
MODELS = [
    "app.users.models",
    "app.organizations.models",
    "app.listings.models",
    "app.orders.models",
    "app.media.models",
    "app.chat.models",
]
```

- [ ] **Step 3: Add table to test cleanup**

In `tests/conftest.py`, add `"chat_messages"` to `_TEST_TABLES` (before `"orders"` so CASCADE works):

```python
_TEST_TABLES = (
    "chat_messages",
    "media",
    "orders",
    "listings",
    "listing_categories",
    "memberships",
    "organization_contacts",
    "payment_details",
    "organizations",
    "users",
)
```

- [ ] **Step 4: Write DB tests**

Create `tests/db/test_chat_message.py`:

```python
from datetime import UTC, datetime

import pytest

from app.chat.models import ChatMessage
from app.core.enums import OrderStatus
from app.core.identifiers import generate_short_id
from app.core.security import hash_password
from app.orders.models import Order
from app.organizations.models import Organization
from app.users.models import User


async def _create_user(email: str = "user@test.com") -> User:
    return await User.create(
        id=generate_short_id(),
        email=email,
        hashed_password=hash_password("pass"),
        phone="+79991234567",
        name="Test",
        surname="User",
    )


async def _create_order(requester: User) -> Order:
    org = await Organization.create(
        id=generate_short_id(),
        inn="7707083893",
        short_name="Test Org",
        full_name="Test Organization LLC",
    )
    # Listing import is needed for FK
    from app.listings.models import Listing, ListingCategory

    category = await ListingCategory.create(name="Test", verified=True)
    listing = await Listing.create(
        id=generate_short_id(),
        name="Test Listing",
        category=category,
        price=1000.00,
        organization=org,
        added_by=requester,
    )
    return await Order.create(
        id=generate_short_id(),
        listing=listing,
        organization=org,
        requester=requester,
        requested_start_date=datetime(2026, 5, 1, tzinfo=UTC).date(),
        requested_end_date=datetime(2026, 5, 10, tzinfo=UTC).date(),
        status=OrderStatus.PENDING,
    )


class TestChatMessageCRUD:
    async def test_create_text_message(self) -> None:
        user = await _create_user()
        order = await _create_order(user)

        msg = await ChatMessage.create(
            order=order,
            sender=user,
            text="Hello",
        )

        assert msg.id is not None
        assert msg.order_id == order.id
        assert msg.sender_id == user.id
        assert msg.text == "Hello"
        assert msg.media == []
        assert msg.read_at is None
        assert msg.created_at is not None

    async def test_create_media_only_message(self) -> None:
        user = await _create_user()
        order = await _create_order(user)

        snapshots = [{"id": "abc", "kind": "photo", "variants": {"large": "media/abc/large.webp"}}]
        msg = await ChatMessage.create(
            order=order,
            sender=user,
            media=snapshots,
        )

        assert msg.text is None
        assert msg.media == snapshots

    async def test_mark_as_read(self) -> None:
        user = await _create_user()
        order = await _create_order(user)

        msg = await ChatMessage.create(order=order, sender=user, text="Hello")
        assert msg.read_at is None

        now = datetime.now(tz=UTC)
        msg.read_at = now
        await msg.save()

        refreshed = await ChatMessage.get(id=msg.id)
        assert refreshed.read_at is not None

    async def test_ordering_newest_first(self) -> None:
        user = await _create_user()
        order = await _create_order(user)

        msg1 = await ChatMessage.create(order=order, sender=user, text="First")
        msg2 = await ChatMessage.create(order=order, sender=user, text="Second")

        messages = await ChatMessage.filter(order=order).all()
        assert messages[0].id == msg2.id
        assert messages[1].id == msg1.id

    async def test_cascade_delete_with_order(self) -> None:
        user = await _create_user()
        order = await _create_order(user)
        await ChatMessage.create(order=order, sender=user, text="Hello")

        assert await ChatMessage.filter(order=order).count() == 1
        await order.delete()
        assert await ChatMessage.filter(order_id=order.id).count() == 0
```

- [ ] **Step 5: Run DB tests**

Run: `task test -- tests/db/test_chat_message.py -v`

Expected: All tests PASS.

- [ ] **Step 6: Run full lint + typecheck**

Run: `task ruff:fix && task mypy`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(chat): add ChatMessage model with DB tests"
```

---

## Task 3: Chat Liveness Logic + Unit Tests

**Files:**
- Create: `app/chat/service.py` (partial — liveness functions only)
- Create: `tests/unit/test_chat_liveness.py`

- [ ] **Step 1: Write unit tests for liveness logic**

Create `tests/unit/test_chat_liveness.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from app.chat.service import get_chat_status
from app.core.enums import OrderStatus

_NOW = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)


class TestGetChatStatus:
    """Tests for get_chat_status(order_status, order_updated_at, last_message_at, cooldown_days, now)."""

    def test_active_order_is_active(self) -> None:
        result = get_chat_status(
            order_status=OrderStatus.PENDING,
            order_updated_at=_NOW - timedelta(days=1),
            last_message_at=None,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "active"

    @pytest.mark.parametrize("status", [
        OrderStatus.PENDING,
        OrderStatus.OFFERED,
        OrderStatus.CONFIRMED,
        OrderStatus.ACTIVE,
    ])
    def test_non_terminal_statuses_are_active(self, status: OrderStatus) -> None:
        result = get_chat_status(
            order_status=status,
            order_updated_at=_NOW,
            last_message_at=None,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "active"

    def test_terminal_within_cooldown_with_message(self) -> None:
        last_msg = _NOW - timedelta(days=3)
        result = get_chat_status(
            order_status=OrderStatus.FINISHED,
            order_updated_at=_NOW - timedelta(days=5),
            last_message_at=last_msg,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "active"

    def test_terminal_past_cooldown_with_message(self) -> None:
        last_msg = _NOW - timedelta(days=10)
        result = get_chat_status(
            order_status=OrderStatus.FINISHED,
            order_updated_at=_NOW - timedelta(days=12),
            last_message_at=last_msg,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "read_only"

    def test_terminal_no_messages_within_cooldown(self) -> None:
        result = get_chat_status(
            order_status=OrderStatus.REJECTED,
            order_updated_at=_NOW - timedelta(days=3),
            last_message_at=None,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "active"

    def test_terminal_no_messages_past_cooldown(self) -> None:
        result = get_chat_status(
            order_status=OrderStatus.REJECTED,
            order_updated_at=_NOW - timedelta(days=10),
            last_message_at=None,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "read_only"

    @pytest.mark.parametrize("status", [
        OrderStatus.FINISHED,
        OrderStatus.REJECTED,
        OrderStatus.DECLINED,
        OrderStatus.CANCELED_BY_USER,
        OrderStatus.CANCELED_BY_ORGANIZATION,
    ])
    def test_all_terminal_statuses_respect_cooldown(self, status: OrderStatus) -> None:
        # Just past cooldown
        last_msg = _NOW - timedelta(days=8)
        result = get_chat_status(
            order_status=status,
            order_updated_at=_NOW - timedelta(days=10),
            last_message_at=last_msg,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "read_only"

    def test_cooldown_boundary_exact(self) -> None:
        # Exactly at cooldown boundary — still active (<=)
        last_msg = _NOW - timedelta(days=7)
        result = get_chat_status(
            order_status=OrderStatus.FINISHED,
            order_updated_at=_NOW - timedelta(days=10),
            last_message_at=last_msg,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "read_only"

    def test_cooldown_boundary_just_before(self) -> None:
        last_msg = _NOW - timedelta(days=7) + timedelta(seconds=1)
        result = get_chat_status(
            order_status=OrderStatus.FINISHED,
            order_updated_at=_NOW - timedelta(days=10),
            last_message_at=last_msg,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "active"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `task test -- tests/unit/test_chat_liveness.py -v`

Expected: FAIL — `ImportError: cannot import name 'get_chat_status' from 'app.chat.service'`

- [ ] **Step 3: Implement liveness logic**

Create `app/chat/service.py`:

```python
from datetime import UTC, datetime, timedelta

from app.core.enums import OrderStatus

_TERMINAL_STATUSES = frozenset({
    OrderStatus.FINISHED,
    OrderStatus.REJECTED,
    OrderStatus.DECLINED,
    OrderStatus.CANCELED_BY_USER,
    OrderStatus.CANCELED_BY_ORGANIZATION,
})


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `task test -- tests/unit/test_chat_liveness.py -v`

Expected: All PASS.

- [ ] **Step 5: Run lint + typecheck**

Run: `task ruff:fix && task mypy`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(chat): add chat liveness logic with unit tests"
```

---

## Task 4: Chat Schemas + Rate Limiter

**Files:**
- Create: `app/chat/schemas.py`
- Create: `tests/unit/test_chat_rate_limiter.py`

- [ ] **Step 1: Create chat schemas**

Create `app/chat/schemas.py`:

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MediaAttachmentRead(BaseModel):
    id: str
    kind: str
    urls: dict[str, str]
    original_filename: str
    content_type: str


class MessageRead(BaseModel):
    id: UUID
    side: str
    name: str
    text: str | None
    media: list[MediaAttachmentRead]
    created_at: datetime
    read_at: datetime | None


class ChatStatusResponse(BaseModel):
    status: str
    unread_count: int
```

- [ ] **Step 2: Write rate limiter tests**

Create `tests/unit/test_chat_rate_limiter.py`:

```python
from unittest.mock import patch

from app.chat.websocket import RateLimiter


class TestRateLimiter:
    def test_allows_under_limit(self) -> None:
        limiter = RateLimiter(max_per_minute=5)
        for _ in range(5):
            assert limiter.allow() is True

    def test_blocks_over_limit(self) -> None:
        limiter = RateLimiter(max_per_minute=3)
        for _ in range(3):
            assert limiter.allow() is True
        assert limiter.allow() is False

    def test_resets_after_window(self) -> None:
        limiter = RateLimiter(max_per_minute=2)
        assert limiter.allow() is True
        assert limiter.allow() is True
        assert limiter.allow() is False

        # Simulate time passing beyond the window
        with patch("time.monotonic", return_value=limiter._window_start + 61):
            assert limiter.allow() is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `task test -- tests/unit/test_chat_rate_limiter.py -v`

Expected: FAIL — `ImportError: cannot import name 'RateLimiter' from 'app.chat.websocket'`

- [ ] **Step 4: Create websocket module with RateLimiter**

Create `app/chat/websocket.py` (partial — rate limiter only for now):

```python
import time


class RateLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._window_start = time.monotonic()
        self._count = 0

    def allow(self) -> bool:
        now = time.monotonic()
        if now - self._window_start >= 60:
            self._window_start = now
            self._count = 0
        if self._count >= self._max:
            return False
        self._count += 1
        return True
```

- [ ] **Step 5: Run tests**

Run: `task test -- tests/unit/test_chat_rate_limiter.py -v`

Expected: All PASS.

- [ ] **Step 6: Run lint + typecheck**

Run: `task ruff:fix && task mypy`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(chat): add schemas and rate limiter with unit tests"
```

---

## Task 5: Chat Service — Send, Read, Mark Read, Status

**Files:**
- Modify: `app/chat/service.py`

This task extends the service module with the core business logic functions. Tests will run as part of the E2E tests in Task 10 since these functions require DB + storage.

- [ ] **Step 1: Add imports and helper functions to service.py**

Add to `app/chat/service.py` (after existing `get_chat_status` function):

```python
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.chat.models import ChatMessage
from app.chat.schemas import ChatStatusResponse, MediaAttachmentRead, MessageRead
from app.core.config import get_settings
from app.core.enums import MediaOwnerType, MediaStatus, OrderStatus
from app.core.exceptions import AppValidationError, NotFoundError, PermissionDeniedError
from app.core.pagination import CursorParams, PaginatedResponse, paginate
from app.media.models import Media
from app.media.storage import StorageClient, get_storage
from app.orders.models import Order
from app.users.models import User

_TERMINAL_STATUSES = frozenset({
    OrderStatus.FINISHED,
    OrderStatus.REJECTED,
    OrderStatus.DECLINED,
    OrderStatus.CANCELED_BY_USER,
    OrderStatus.CANCELED_BY_ORGANIZATION,
})


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
        result.append(MediaAttachmentRead(
            id=snap["id"],
            kind=snap["kind"],
            urls=urls,
            original_filename=snap["original_filename"],
            content_type=snap["content_type"],
        ))
    return result


async def _to_message_read(
    msg: ChatMessage,
    order: Order,
    storage: StorageClient,
) -> MessageRead:
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
        created_at=msg.created_at,
        read_at=msg.read_at,
    )


async def compute_chat_status_for_order(order: Order, user: User) -> ChatStatusResponse:
    settings = get_settings()
    last_msg = await ChatMessage.filter(order_id=order.id).order_by("-created_at").first()
    last_message_at = last_msg.created_at if last_msg else None
    status = get_chat_status(
        order_status=OrderStatus(order.status),
        order_updated_at=order.updated_at,
        last_message_at=last_message_at,
        cooldown_days=settings.chat.cooldown_days,
    )
    unread_count = await ChatMessage.filter(
        order_id=order.id,
        read_at=None,
    ).exclude(sender_id=user.id).count()
    return ChatStatusResponse(status=status, unread_count=unread_count)


async def send_message(
    order: Order,
    user: User,
    text: str | None,
    media_ids: list[str],
) -> MessageRead:
    settings = get_settings()

    if not text and not media_ids:
        raise AppValidationError("Message must have text or attachments")
    if text and len(text) > settings.chat.max_message_length:
        raise AppValidationError(f"Message exceeds maximum length of {settings.chat.max_message_length}")
    if len(media_ids) > settings.chat.max_attachments_per_message:
        raise AppValidationError(f"Maximum {settings.chat.max_attachments_per_message} attachments per message")

    # Validate and snapshot media
    media_snapshots: list[dict[str, Any]] = []
    media_records: list[Media] = []
    for mid_str in media_ids:
        try:
            mid = UUID(mid_str)
        except ValueError as e:
            raise AppValidationError(f"Invalid media ID: {mid_str}") from e
        media = await Media.get_or_none(id=mid)
        if media is None:
            raise NotFoundError(f"Media {mid_str} not found")
        if media.status != MediaStatus.READY:
            raise AppValidationError(f"Media {mid_str} is not ready")
        if media.uploaded_by_id != user.id:
            raise PermissionDeniedError(f"Media {mid_str} was not uploaded by you")
        media_snapshots.append({
            "id": str(media.id),
            "kind": media.kind.value,
            "variants": media.variants,
            "original_filename": media.original_filename,
            "content_type": media.content_type,
        })
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
) -> PaginatedResponse[MessageRead]:
    qs = ChatMessage.filter(order_id=order.id).prefetch_related("sender")
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-created_at", "-id"))

    storage = get_storage()
    reads: list[MessageRead] = []
    for msg in items:
        reads.append(await _to_message_read(msg, order, storage))

    return PaginatedResponse(items=reads, next_cursor=next_cursor, has_more=has_more)


async def mark_messages_read(order_id: str, user_id: str, until_message_id: str) -> int:
    until_msg = await ChatMessage.get_or_none(id=until_message_id, order_id=order_id)
    if until_msg is None:
        raise NotFoundError("Message not found")

    count: int = await ChatMessage.filter(
        order_id=order_id,
        read_at=None,
        created_at__lte=until_msg.created_at,
    ).exclude(sender_id=user_id).update(read_at=datetime.now(tz=UTC))

    return count
```

- [ ] **Step 2: Run lint + typecheck**

Run: `task ruff:fix && task mypy`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat(chat): add chat service — send message, read history, mark read, status"
```

---

## Task 6: Chat Dependencies + REST Router

**Files:**
- Create: `app/chat/dependencies.py`
- Create: `app/chat/router.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create chat dependencies**

Create `app/chat/dependencies.py`:

```python
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
```

- [ ] **Step 2: Create REST router**

Create `app/chat/router.py`:

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
    return await service.get_messages(order, params)


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
    return await service.get_messages(order, params)


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

- [ ] **Step 3: Register router in main.py**

In `app/main.py`, add the chat router import and registration:

```python
# Add import
from app.chat.router import router as chat_router

# In create_app(), add after media_router:
application.include_router(chat_router)
```

- [ ] **Step 4: Run lint + typecheck**

Run: `task ruff:fix && task mypy`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(chat): add REST endpoints for message history and chat status"
```

---

## Task 7: Redis Pub/Sub Module

**Files:**
- Create: `app/chat/pubsub.py`
- Modify: `app/main.py` (init/close Redis in lifespan)

- [ ] **Step 1: Create pubsub module**

Create `app/chat/pubsub.py`:

```python
import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

logger = logging.getLogger(__name__)

_redis: Redis | None = None


async def init_redis(url: str) -> None:
    global _redis  # noqa: PLW0603
    _redis = Redis.from_url(url, decode_responses=True)
    logger.info("Redis pub/sub client initialized")


async def close_redis() -> None:
    global _redis  # noqa: PLW0603
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis pub/sub client closed")


def get_redis() -> Redis:
    if _redis is None:
        msg = "Redis not initialized — call init_redis() first"
        raise RuntimeError(msg)
    return _redis


async def publish(channel: str, data: dict[str, Any]) -> None:
    redis = get_redis()
    await redis.publish(channel, json.dumps(data))


async def subscribe(channel: str) -> PubSub:
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    return pubsub
```

- [ ] **Step 2: Initialize Redis in app lifespan**

In `app/main.py`, modify the lifespan to init/close Redis:

```python
# Add import
from app.chat.pubsub import close_redis, init_redis

# In lifespan(), after storage.ensure_bucket():
        await init_redis(settings.worker.redis_url)
        yield
        await close_redis()
    shutdown_observability()
```

The full lifespan should become:

```python
@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    setup_observability()
    config = get_tortoise_config()
    async with RegisterTortoise(
        application,
        config=config,
        generate_schemas=True,
    ):
        await _seed_categories()
        settings = get_settings()
        storage = init_storage(
            endpoint_url=settings.storage.endpoint_url,
            access_key=settings.storage.access_key,
            secret_key=settings.storage.secret_key,
            bucket=settings.storage.bucket,
        )
        await storage.ensure_bucket()
        await init_redis(settings.worker.redis_url)
        yield
        await close_redis()
    shutdown_observability()
```

- [ ] **Step 3: Run lint + typecheck**

Run: `task ruff:fix && task mypy`

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(chat): add Redis pub/sub module and initialize in app lifespan"
```

---

## Task 8: WebSocket Handler

**Files:**
- Modify: `app/chat/websocket.py` (extend with connection registry + WS handler)
- Modify: `app/main.py` (register WS router)

- [ ] **Step 1: Implement the full WebSocket module**

Replace `app/chat/websocket.py` with the complete implementation:

```python
import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio.client import PubSub

from app.chat import service
from app.chat.pubsub import publish, subscribe
from app.core.config import get_settings
from app.core.enums import MembershipRole, MembershipStatus, OrderStatus, UserRole
from app.core.security import decode_access_token
from app.orders.models import Order
from app.organizations.models import Membership
from app.users.models import User

logger = logging.getLogger(__name__)

ws_router = APIRouter()


# --- Rate Limiter ---


class RateLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._window_start = time.monotonic()
        self._count = 0

    def allow(self) -> bool:
        now = time.monotonic()
        if now - self._window_start >= 60:
            self._window_start = now
            self._count = 0
        if self._count >= self._max:
            return False
        self._count += 1
        return True


# --- Connection Registry ---


_connections: dict[str, set[tuple[str, WebSocket]]] = {}


def _add_connection(order_id: str, user_id: str, ws: WebSocket) -> None:
    if order_id not in _connections:
        _connections[order_id] = set()
    _connections[order_id].add((user_id, ws))


def _remove_connection(order_id: str, user_id: str, ws: WebSocket) -> None:
    conns = _connections.get(order_id)
    if conns:
        conns.discard((user_id, ws))
        if not conns:
            del _connections[order_id]


# --- Auth Helpers ---


async def _authenticate_ws(token: str | None) -> User | None:
    if token is None:
        return None
    try:
        subject = decode_access_token(token)
    except ValueError:
        return None
    user = await User.get_or_none(id=subject)
    if user is None or user.role == UserRole.SUSPENDED:
        return None
    return user


async def _is_chat_participant(user: User, order: Order) -> bool:
    if order.requester_id == user.id:
        return True
    membership = await Membership.get_or_none(
        organization_id=order.organization_id,
        user=user,
        status=MembershipStatus.MEMBER,
        role__in=[MembershipRole.ADMIN, MembershipRole.EDITOR],
    )
    return membership is not None


def _get_side(user: User, order: Order) -> str:
    return "requester" if user.id == order.requester_id else "organization"


# --- Redis Listener ---


async def _listen_redis(pubsub: PubSub, ws: WebSocket, user_id: str) -> None:
    async for raw_message in pubsub.listen():
        if raw_message["type"] != "message":
            continue
        payload: dict[str, Any] = json.loads(raw_message["data"])
        sender_id = payload.pop("_sender_id", None)
        msg_type = payload.get("type")
        # Don't echo typing/read back to the sender
        if msg_type in ("typing", "read") and sender_id == user_id:
            continue
        await ws.send_json(payload)


# --- Client Listener ---


async def _listen_client(
    ws: WebSocket,
    order: Order,
    user: User,
    rate_limiter: RateLimiter,
    chat_active: bool,
) -> None:
    while True:
        raw = await ws.receive_text()
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_json({"type": "error", "data": {"code": "invalid_json", "detail": "Invalid JSON"}})
            continue

        msg_type = data.get("type")

        if msg_type == "message":
            if not chat_active:
                await ws.send_json({
                    "type": "error",
                    "data": {"code": "read_only", "detail": "Chat is read-only"},
                })
                continue
            if not rate_limiter.allow():
                await ws.send_json({
                    "type": "error",
                    "data": {"code": "rate_limited", "detail": "Too many messages, slow down"},
                })
                continue
            try:
                message_read = await service.send_message(
                    order,
                    user,
                    data.get("text"),
                    data.get("media_ids", []),
                )
            except Exception as exc:  # noqa: BLE001
                await ws.send_json({
                    "type": "error",
                    "data": {"code": "validation_error", "detail": str(exc)},
                })
                continue

            broadcast = {
                "type": "message",
                "data": json.loads(message_read.model_dump_json()),
                "_sender_id": user.id,
            }
            await publish(f"chat:{order.id}", broadcast)

            # Enqueue notification job for offline users
            try:
                from app.media.worker import get_arq_pool

                pool = await get_arq_pool()
                await pool.enqueue_job("notify_new_chat_message", order.id, str(message_read.id))
            except Exception:  # noqa: BLE001
                logger.warning("Failed to enqueue chat notification job", exc_info=True)

        elif msg_type == "typing":
            if not chat_active:
                continue
            side = _get_side(user, order)
            await publish(f"chat:{order.id}", {
                "type": "typing",
                "data": {"side": side, "is_typing": bool(data.get("is_typing", False))},
                "_sender_id": user.id,
            })

        elif msg_type == "read":
            until_id = data.get("until_message_id")
            if not until_id:
                continue
            try:
                await service.mark_messages_read(order.id, user.id, until_id)
            except Exception:  # noqa: BLE001
                logger.warning("Failed to mark messages as read", exc_info=True)
                continue
            side = _get_side(user, order)
            await publish(f"chat:{order.id}", {
                "type": "read",
                "data": {"side": side, "until_message_id": until_id},
                "_sender_id": user.id,
            })


# --- WebSocket Endpoint ---


@ws_router.websocket("/api/v1/orders/{order_id}/chat/ws")
async def chat_websocket(websocket: WebSocket, order_id: str, token: str | None = None) -> None:
    user = await _authenticate_ws(token)
    if user is None:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    order = await Order.get_or_none(id=order_id)
    if order is None:
        await websocket.close(code=4004, reason="Order not found")
        return

    if not await _is_chat_participant(user, order):
        await websocket.close(code=4003, reason="Not a chat participant")
        return

    await websocket.accept()

    settings = get_settings()
    status_resp = await service.compute_chat_status_for_order(order, user)
    chat_active = status_resp.status == "active"
    await websocket.send_json({"type": "connected", "data": {"chat_status": status_resp.status}})

    _add_connection(order_id, user.id, websocket)
    pubsub = await subscribe(f"chat:{order_id}")
    rate_limiter = RateLimiter(max_per_minute=settings.chat.rate_limit_per_minute)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_listen_redis(pubsub, websocket, user.id))
            tg.create_task(_listen_client(websocket, order, user, rate_limiter, chat_active))
    except* WebSocketDisconnect:
        pass
    except* Exception:
        logger.warning("WebSocket error for order %s", order_id, exc_info=True)
    finally:
        _remove_connection(order_id, user.id, websocket)
        await pubsub.unsubscribe(f"chat:{order_id}")
        await pubsub.aclose()
```

- [ ] **Step 2: Register WebSocket router in main.py**

In `app/main.py`, add the WebSocket router:

```python
# Add import
from app.chat.websocket import ws_router as chat_ws_router

# In create_app(), after chat_router:
application.include_router(chat_ws_router)
```

- [ ] **Step 3: Run lint + typecheck**

Run: `task ruff:fix && task mypy`

Expected: PASS. Address any type issues (especially around `json.loads` return types, WebSocket exception handling).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(chat): add WebSocket handler with connection registry and rate limiter"
```

---

## Task 9: Media Worker Update + Notification Stub

**Files:**
- Modify: `app/media/worker.py:19-23`
- Add notification job to worker

- [ ] **Step 1: Add chat context to variant set mapping**

In `app/media/worker.py`, add the chat mapping:

```python
_CONTEXT_TO_VARIANT_SET: dict[str, str] = {
    "user_profile": "profile",
    "org_profile": "profile",
    "listing": "listing",
    "chat": "chat",
}
```

- [ ] **Step 2: Add notification stub job**

In `app/media/worker.py`, add the notification job function after `cleanup_orphans_cron`:

```python
async def notify_new_chat_message(_ctx: dict[Any, Any], order_id: str, message_id: str) -> None:
    """Stub for chat message notifications. Hook point for future push notifications."""
    logger.info("Chat notification: order=%s message=%s (stub — no notification sent)", order_id, message_id)
```

Register it in `WorkerSettings.functions`:

```python
class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        func(cast("WorkerCoroutine", process_media_job), max_tries=3),
        func(cast("WorkerCoroutine", notify_new_chat_message), max_tries=1),
    ]
    # ... rest unchanged
```

- [ ] **Step 3: Run lint + typecheck**

Run: `task ruff:fix && task mypy`

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(chat): add chat media variant set and notification stub job"
```

---

## Task 10: Test Fixtures + E2E Tests

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/e2e/test_chat.py`

- [ ] **Step 1: Add chat fixtures to conftest.py**

In `tests/conftest.py`, add chat-related fixtures after the existing `renter_token` fixture:

```python
from datetime import UTC, datetime, timedelta

from app.chat.models import ChatMessage
from app.core.enums import OrderStatus


@pytest.fixture
async def create_order_for_chat(
    client: AsyncClient,
    create_listing: tuple[str, str, str],
    renter_token: str,
) -> tuple[str, str, str, str]:
    """Create an order in OFFERED status for chat testing.

    Returns (order_id, org_id, org_admin_token, renter_token).
    """
    listing_id, org_id, org_token = create_listing
    tomorrow = (datetime.now(tz=UTC) + timedelta(days=1)).date().isoformat()
    next_week = (datetime.now(tz=UTC) + timedelta(days=7)).date().isoformat()

    # Create order
    resp = await client.post(
        "/api/v1/orders/",
        json={
            "listing_id": listing_id,
            "requested_start_date": tomorrow,
            "requested_end_date": next_week,
        },
        headers={"Authorization": f"Bearer {renter_token}"},
    )
    assert resp.status_code == 201, resp.text
    order_id: str = resp.json()["id"]

    # Offer so order is in a non-pending state with dates
    resp = await client.patch(
        f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
        json={
            "offered_cost": "5000.00",
            "offered_start_date": tomorrow,
            "offered_end_date": next_week,
        },
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert resp.status_code == 200, resp.text

    return order_id, org_id, org_token, renter_token
```

- [ ] **Step 2: Write E2E tests for REST endpoints**

Create `tests/e2e/test_chat.py`:

```python
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.chat.models import ChatMessage
from app.core.enums import OrderStatus
from app.orders.models import Order


pytestmark = pytest.mark.e2e


class TestChatRESTEndpoints:
    async def test_get_messages_empty(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["has_more"] is False

    async def test_get_chat_status_active(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/status",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["unread_count"] == 0

    async def test_get_messages_not_participant(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
        create_user: Any,
    ) -> None:
        order_id, _org_id, _org_token, _renter_token = create_order_for_chat

        _, outsider_token = await create_user(email="outsider@example.com", phone="+79005555555")

        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert resp.status_code == 403

    async def test_get_messages_org_side(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, org_id, org_token, _renter_token = create_order_for_chat

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/messages",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_get_org_chat_status(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        order_id, org_id, org_token, _renter_token = create_order_for_chat

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/status",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"


class TestChatWebSocket:
    async def test_ws_connect_and_receive_connected(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        from httpx_ws import aconnect_ws

        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        async with aconnect_ws(
            f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
            client,
        ) as ws:
            data = await ws.receive_json()
            assert data["type"] == "connected"
            assert data["data"]["chat_status"] == "active"

    async def test_ws_connect_invalid_token(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        from httpx_ws import aconnect_ws
        from httpx_ws._exceptions import WebSocketDisconnect

        order_id, _org_id, _org_token, _renter_token = create_order_for_chat

        with pytest.raises(WebSocketDisconnect) as exc_info:
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token=invalid",
                client,
            ) as ws:
                await ws.receive_json()
        assert exc_info.value.code == 4001

    async def test_ws_connect_not_participant(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
        create_user: Any,
    ) -> None:
        from httpx_ws import aconnect_ws
        from httpx_ws._exceptions import WebSocketDisconnect

        order_id, _org_id, _org_token, _renter_token = create_order_for_chat
        _, outsider_token = await create_user(email="outsider2@example.com", phone="+79005555556")

        with pytest.raises(WebSocketDisconnect) as exc_info:
            async with aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={outsider_token}",
                client,
            ) as ws:
                await ws.receive_json()
        assert exc_info.value.code == 4003

    async def test_ws_send_and_receive_message(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        from httpx_ws import aconnect_ws

        order_id, _org_id, org_token, renter_token = create_order_for_chat

        # Connect both renter and org
        async with (
            aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                client,
            ) as renter_ws,
            aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={org_token}",
                client,
            ) as org_ws,
        ):
            # Drain connected frames
            await renter_ws.receive_json()
            await org_ws.receive_json()

            # Renter sends a message
            await renter_ws.send_json({"type": "message", "text": "Hello org!"})

            # Both should receive the message
            renter_msg = await renter_ws.receive_json()
            assert renter_msg["type"] == "message"
            assert renter_msg["data"]["side"] == "requester"
            assert renter_msg["data"]["text"] == "Hello org!"

            org_msg = await org_ws.receive_json()
            assert org_msg["type"] == "message"
            assert org_msg["data"]["side"] == "requester"
            assert org_msg["data"]["text"] == "Hello org!"

    async def test_ws_typing_indicator(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        import asyncio

        from httpx_ws import aconnect_ws

        order_id, _org_id, org_token, renter_token = create_order_for_chat

        async with (
            aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                client,
            ) as renter_ws,
            aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={org_token}",
                client,
            ) as org_ws,
        ):
            await renter_ws.receive_json()
            await org_ws.receive_json()

            # Renter types
            await renter_ws.send_json({"type": "typing", "is_typing": True})

            # Org should see typing, renter should NOT (no echo)
            org_data = await org_ws.receive_json()
            assert org_data["type"] == "typing"
            assert org_data["data"]["side"] == "requester"
            assert org_data["data"]["is_typing"] is True

    async def test_ws_read_receipt(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        from httpx_ws import aconnect_ws

        order_id, _org_id, org_token, renter_token = create_order_for_chat

        async with (
            aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
                client,
            ) as renter_ws,
            aconnect_ws(
                f"/api/v1/orders/{order_id}/chat/ws?token={org_token}",
                client,
            ) as org_ws,
        ):
            await renter_ws.receive_json()
            await org_ws.receive_json()

            # Renter sends message
            await renter_ws.send_json({"type": "message", "text": "Read this"})
            renter_msg = await renter_ws.receive_json()
            msg_id = renter_msg["data"]["id"]
            await org_ws.receive_json()  # drain message

            # Org marks as read
            await org_ws.send_json({"type": "read", "until_message_id": msg_id})

            # Renter should get read receipt
            read_receipt = await renter_ws.receive_json()
            assert read_receipt["type"] == "read"
            assert read_receipt["data"]["side"] == "organization"
            assert read_receipt["data"]["until_message_id"] == msg_id

            # Verify DB was updated
            from app.chat.models import ChatMessage

            db_msg = await ChatMessage.get(id=msg_id)
            assert db_msg.read_at is not None

    async def test_ws_read_only_chat(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        from httpx_ws import aconnect_ws

        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        # Move order to terminal state with old updated_at
        order = await Order.get(id=order_id)
        order.status = OrderStatus.REJECTED
        await order.save()
        # Force updated_at to past
        from tortoise import connections

        conn = connections.get("default")
        await conn.execute_query(
            f"UPDATE orders SET updated_at = updated_at - interval '30 days' WHERE id = '{order_id}'"
        )

        async with aconnect_ws(
            f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
            client,
        ) as ws:
            connected = await ws.receive_json()
            assert connected["data"]["chat_status"] == "read_only"

            # Try to send message — should get error
            await ws.send_json({"type": "message", "text": "Too late"})
            error = await ws.receive_json()
            assert error["type"] == "error"
            assert error["data"]["code"] == "read_only"

    async def test_messages_visible_in_rest_after_ws_send(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        from httpx_ws import aconnect_ws

        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        # Send message via WebSocket
        async with aconnect_ws(
            f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
            client,
        ) as ws:
            await ws.receive_json()  # connected
            await ws.send_json({"type": "message", "text": "Persisted!"})
            await ws.receive_json()  # message echo

        # Verify via REST
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/messages",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["text"] == "Persisted!"
        assert items[0]["side"] == "requester"

    async def test_unread_count(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        from httpx_ws import aconnect_ws

        order_id, org_id, org_token, renter_token = create_order_for_chat

        # Renter sends 2 messages
        async with aconnect_ws(
            f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
            client,
        ) as ws:
            await ws.receive_json()
            await ws.send_json({"type": "message", "text": "Msg 1"})
            await ws.receive_json()
            await ws.send_json({"type": "message", "text": "Msg 2"})
            await ws.receive_json()

        # Check org unread count
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/chat/status",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["unread_count"] == 2

        # Renter should have 0 unread (they sent those messages)
        resp = await client.get(
            f"/api/v1/orders/{order_id}/chat/status",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["unread_count"] == 0

    async def test_message_validation_empty(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        from httpx_ws import aconnect_ws

        order_id, _org_id, _org_token, renter_token = create_order_for_chat

        async with aconnect_ws(
            f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
            client,
        ) as ws:
            await ws.receive_json()
            await ws.send_json({"type": "message"})
            error = await ws.receive_json()
            assert error["type"] == "error"
            assert error["data"]["code"] == "validation_error"

    async def test_message_author_display(
        self,
        client: AsyncClient,
        create_order_for_chat: tuple[str, str, str, str],
    ) -> None:
        from httpx_ws import aconnect_ws

        order_id, org_id, org_token, renter_token = create_order_for_chat

        # Renter sends
        async with aconnect_ws(
            f"/api/v1/orders/{order_id}/chat/ws?token={renter_token}",
            client,
        ) as ws:
            await ws.receive_json()
            await ws.send_json({"type": "message", "text": "Hi"})
            msg = await ws.receive_json()
            assert msg["data"]["side"] == "requester"
            assert msg["data"]["name"] == "Renter Testov"

        # Org sends
        async with aconnect_ws(
            f"/api/v1/orders/{order_id}/chat/ws?token={org_token}",
            client,
        ) as ws:
            await ws.receive_json()
            await ws.send_json({"type": "message", "text": "Reply"})
            msg = await ws.receive_json()
            assert msg["data"]["side"] == "organization"
            # Org short name comes from Dadata — check it's not empty
            assert len(msg["data"]["name"]) > 0
```

- [ ] **Step 3: Run E2E tests**

Run: `task test -- tests/e2e/test_chat.py -v`

Expected: All PASS. If any fail, debug and fix the service/websocket code.

**Note:** E2E tests require PostgreSQL, Redis, and MinIO running. If `httpx-ws` API differs slightly, adjust the test connection code (check `aconnect_ws` signature and exception types).

- [ ] **Step 4: Run the full test suite**

Run: `task test`

Expected: All tests PASS, including existing tests (no regressions).

- [ ] **Step 5: Run lint + typecheck**

Run: `task ruff:fix && task mypy`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "test(chat): add E2E tests for chat WebSocket and REST endpoints"
```

---

## Task 11: Update business-logic.md

**Files:**
- Modify: `docs/business-logic.md`

- [ ] **Step 1: Add chat section to business logic doc**

Read the current `docs/business-logic.md` and add a new section (after the Orders section) documenting:

- Chat is implicitly created with each order
- Participants: requester + org editors/admins
- Message authorship: requester shows full name, org shows org short name
- Chat liveness: active during non-terminal order status, active during cooldown after terminal, read-only after cooldown expires
- Cooldown: configurable (default 7 days), measured from last message or order terminal timestamp
- Messages are immutable (no edit, no delete)
- Media attachments reuse the media system with chat-specific variants
- Read receipts are persisted, typing indicators are ephemeral
- Real-time delivery via WebSocket, REST for history

- [ ] **Step 2: Commit**

```bash
git add docs/business-logic.md
git commit -m "docs: add chat feature to business logic documentation"
```

---

## Task 12: Frontend Integration Guide

**Files:**
- Create: `docs/chat-integration-guide.md`

- [ ] **Step 1: Write comprehensive frontend integration guide**

Create `docs/chat-integration-guide.md` covering:

**Authentication:**
- JWT token passed as `?token=` query parameter for WebSocket
- Standard `Authorization: Bearer {token}` header for REST endpoints

**WebSocket Protocol:**
- Connection URL: `ws://host/api/v1/orders/{order_id}/chat/ws?token={jwt}`
- All frame types with examples (connected, message, typing, read, error)
- Client-to-server frame format
- Server-to-client frame format

**REST Endpoints:**
- `GET /api/v1/orders/{order_id}/chat/messages` — user-side history
- `GET /api/v1/orders/{order_id}/chat/status` — user-side status
- `GET /api/v1/organizations/{org_id}/orders/{order_id}/chat/messages` — org-side history
- `GET /api/v1/organizations/{org_id}/orders/{order_id}/chat/status` — org-side status
- Pagination (cursor-based), response shapes

**Media Attachment Flow:**
1. `POST /api/v1/media/upload-url` with `context: "chat"`, `kind: "photo"|"video"|"document"`
2. Upload to returned presigned URL
3. `POST /api/v1/media/{id}/confirm`
4. Poll `GET /api/v1/media/{id}/status` until `ready`
5. Send WebSocket message with `media_ids: [...]`

**Error Codes:**
- `rate_limited`, `read_only`, `validation_error`, `invalid_json`

**Chat States:**
- `active` — can send messages, typing, read receipts
- `read_only` — can only read history and mark messages as read

**Example Sequences:**
- Connect, send message, receive echo
- Two-party conversation
- Sending with attachments
- Handling read-only state

- [ ] **Step 2: Commit**

```bash
git add docs/chat-integration-guide.md
git commit -m "docs: add frontend integration guide for chat API"
```

---

## Post-implementation checklist

After all tasks are complete:

- [ ] Run `task ci` (lint + typecheck + test) — must all pass
- [ ] Review the full diff against the spec (`docs/superpowers/specs/2026-03-31-order-chat-design.md`)
- [ ] Generate migration for production: `task db:makemigrations` (for `chat_messages` table + `media.owner_id` max_length change)
