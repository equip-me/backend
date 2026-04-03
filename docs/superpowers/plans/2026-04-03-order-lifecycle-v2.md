# Order Lifecycle V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the order lifecycle to add missing transitions, a reservation model, expiration, and background job-based auto-transitions.

**Architecture:** Replace the current 9-status state machine with a new 9-status machine (adding ACCEPTED/EXPIRED, removing REJECTED/DECLINED). Add a Reservation model that tracks confirmed date ranges per listing. Replace lazy read-triggered auto-transitions with targeted ARQ jobs + a daily safety-net sweep. Extract the monolithic `app/media/worker.py` into a modular `app/worker/` package.

**Tech Stack:** Python 3.14, FastAPI, Tortoise ORM, ARQ (Redis), Pydantic v2, pytest + httpx

**Spec:** `docs/superpowers/specs/2026-04-03-order-lifecycle-v2-design.md`

**Python Conventions (for subagents):**
- No `# type: ignore` — fix the type error or restructure
- No `from __future__ import annotations` — Pydantic v2 and Tortoise need runtime types
- Strict mypy — every function fully typed, no implicit `Any`
- Ruff — line length 119, `select = ["ALL"]` with specific ignores (see pyproject.toml)
- 6-char short string IDs on user-facing models; UUID on internal models
- Async everywhere
- Run `task ruff:fix` and `task mypy` after each implementation step

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `app/reservations/__init__.py` | Package init |
| `app/reservations/models.py` | Reservation Tortoise ORM model |
| `app/reservations/schemas.py` | ReservationRead Pydantic schema |
| `app/reservations/service.py` | Create/delete/query reservations, overlap validation |
| `app/reservations/router.py` | `GET /api/v1/listings/{listing_id}/reservations` |
| `app/worker/__init__.py` | Package init |
| `app/worker/__main__.py` | Entrypoint: `python -m app.worker` |
| `app/worker/settings.py` | Shared WorkerSettings, redis pool helper, aggregated functions/crons |
| `app/worker/media.py` | Media jobs moved from `app/media/worker.py` |
| `app/worker/chat.py` | Chat notification stub moved from `app/media/worker.py` |
| `app/worker/orders.py` | `expire_order`, `activate_order`, `finish_order`, `order_sweep_cron` |
| `tests/unit/test_order_state_machine.py` | Rewrite for new state machine (same file, full rewrite) |
| `tests/db/test_reservations.py` | Reservation model: creation, overlap, cleanup |
| `tests/e2e/test_order_happy_path.py` | Rewrite for new lifecycle (same file, full rewrite) |
| `tests/e2e/test_order_cancellations.py` | Rewrite for new lifecycle (same file, full rewrite) |
| `tests/db/test_order_worker.py` | Worker order jobs: expire, activate, finish, sweep |
| `tests/e2e/test_reservations.py` | Reservation calendar endpoint, overlap rejection |

### Modified Files

| File | Changes |
|------|---------|
| `app/core/enums.py` | Add ACCEPTED, EXPIRED to OrderStatus. Add ACCEPT_BY_USER, APPROVE_BY_ORG, EXPIRE to OrderAction. Remove REJECTED, DECLINED, IN_RENT. Remove REJECT_BY_ORG, CONFIRM_BY_USER, DECLINE_BY_USER. |
| `app/orders/state_machine.py` | Rewrite transition table. Remove `maybe_auto_transition`. |
| `app/orders/models.py` | No structural changes (status field max_length may need update) |
| `app/orders/schemas.py` | No changes needed |
| `app/orders/service.py` | Rewrite: remove auto-transition, add accept/approve/cancel-from-any, add job scheduling |
| `app/orders/router.py` | Remove confirm/decline/reject endpoints. Add accept/approve. Update cancel docstrings. |
| `app/orders/dependencies.py` | No changes needed |
| `app/core/database.py` | Add `app.reservations.models` to MODELS list |
| `app/core/config.py` | (no changes needed — worker config already exists) |
| `app/main.py` | Add reservations router include |
| `app/media/worker.py` | Delete (replaced by `app/worker/` package) |
| `app/media/service.py` | Update `get_arq_pool` import path |
| `app/chat/websocket.py` | Update `get_arq_pool` import path |
| `tests/conftest.py` | Add `reservations` to `_TEST_TABLES`, update `create_order_for_chat` fixture |
| `tests/db/conftest.py` | Update `get_arq_pool` mock path |
| `tests/db/test_worker.py` | Update import paths from `app.media.worker` to `app.worker.media` |
| `tests/e2e/test_order_happy_path.py` | Full rewrite for new lifecycle |
| `tests/e2e/test_order_cancellations.py` | Full rewrite for new lifecycle |
| `tests/e2e/test_full_rental_journey.py` | Update imports and remove `in_rent` assertions |
| `tests/e2e/test_org_lifecycle.py` | Update worker import path |
| `tests/e2e/test_user_registration.py` | Update worker import path |
| `tests/e2e/test_listing_catalog.py` | Update worker import path |
| `tests/e2e/test_e2e_media.py` | Update worker import path |
| `Taskfile.yml` | Update worker command to `python -m app.worker` |
| `docker-compose.prod.yml` | Update worker command to `python -m app.worker` |

---

## Task 1: Update Enums

**Files:**
- Modify: `app/core/enums.py:28-56`

- [ ] **Step 1: Update ListingStatus — remove IN_RENT**

In `app/core/enums.py`, replace the `ListingStatus` enum:

```python
class ListingStatus(StrEnum):
    HIDDEN = "hidden"
    PUBLISHED = "published"
    ARCHIVED = "archived"
```

- [ ] **Step 2: Update OrderStatus — add ACCEPTED, EXPIRED; remove REJECTED, DECLINED**

Replace the `OrderStatus` enum:

```python
class OrderStatus(StrEnum):
    PENDING = "pending"
    OFFERED = "offered"
    ACCEPTED = "accepted"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    FINISHED = "finished"
    CANCELED_BY_USER = "canceled_by_user"
    CANCELED_BY_ORGANIZATION = "canceled_by_organization"
    EXPIRED = "expired"
```

- [ ] **Step 3: Update OrderAction — add ACCEPT_BY_USER, APPROVE_BY_ORG, EXPIRE; remove old actions**

Replace the `OrderAction` enum:

```python
class OrderAction(StrEnum):
    OFFER_BY_ORG = "offer_by_org"
    ACCEPT_BY_USER = "accept_by_user"
    APPROVE_BY_ORG = "approve_by_org"
    CANCEL_BY_USER = "cancel_by_user"
    CANCEL_BY_ORG = "cancel_by_org"
    ACTIVATE = "activate"
    FINISH = "finish"
    EXPIRE = "expire"
```

- [ ] **Step 4: Verify ruff passes**

Run: `task ruff:fix`

There will be import errors from files still referencing removed enum values — that's expected, we'll fix those in subsequent tasks.

- [ ] **Step 5: Commit**

```bash
git add app/core/enums.py
git commit -m "refactor(enums): update OrderStatus, OrderAction, ListingStatus for lifecycle v2"
```

---

## Task 2: Rewrite State Machine

**Files:**
- Modify: `app/orders/state_machine.py`
- Modify: `tests/unit/test_order_state_machine.py`

- [ ] **Step 1: Write failing tests for new state machine**

Rewrite `tests/unit/test_order_state_machine.py` entirely:

```python
import pytest

from app.core.enums import OrderAction, OrderStatus
from app.core.exceptions import AppValidationError
from app.orders.state_machine import transition


class TestValidTransitions:
    # PENDING transitions
    def test_pending_offer(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.OFFER_BY_ORG) == OrderStatus.OFFERED

    def test_pending_cancel_by_user(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_pending_cancel_by_org(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    def test_pending_expire(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.EXPIRE) == OrderStatus.EXPIRED

    # OFFERED transitions
    def test_offered_reoffer(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.OFFER_BY_ORG) == OrderStatus.OFFERED

    def test_offered_accept(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.ACCEPT_BY_USER) == OrderStatus.ACCEPTED

    def test_offered_cancel_by_user(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_offered_cancel_by_org(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    def test_offered_expire(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.EXPIRE) == OrderStatus.EXPIRED

    # ACCEPTED transitions
    def test_accepted_reoffer(self) -> None:
        assert transition(OrderStatus.ACCEPTED, OrderAction.OFFER_BY_ORG) == OrderStatus.OFFERED

    def test_accepted_approve(self) -> None:
        assert transition(OrderStatus.ACCEPTED, OrderAction.APPROVE_BY_ORG) == OrderStatus.CONFIRMED

    def test_accepted_cancel_by_user(self) -> None:
        assert transition(OrderStatus.ACCEPTED, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_accepted_cancel_by_org(self) -> None:
        assert transition(OrderStatus.ACCEPTED, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    def test_accepted_expire(self) -> None:
        assert transition(OrderStatus.ACCEPTED, OrderAction.EXPIRE) == OrderStatus.EXPIRED

    # CONFIRMED transitions
    def test_confirmed_activate(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.ACTIVATE) == OrderStatus.ACTIVE

    def test_confirmed_cancel_by_user(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_confirmed_cancel_by_org(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    # ACTIVE transitions
    def test_active_finish(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.FINISH) == OrderStatus.FINISHED

    def test_active_cancel_by_user(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_active_cancel_by_org(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION


class TestTerminalStates:
    @pytest.mark.parametrize(
        "terminal_status",
        [
            OrderStatus.FINISHED,
            OrderStatus.CANCELED_BY_USER,
            OrderStatus.CANCELED_BY_ORGANIZATION,
            OrderStatus.EXPIRED,
        ],
    )
    @pytest.mark.parametrize(
        "action",
        list(OrderAction),
    )
    def test_terminal_states_reject_all_actions(
        self, terminal_status: OrderStatus, action: OrderAction
    ) -> None:
        with pytest.raises(AppValidationError):
            transition(terminal_status, action)


class TestInvalidTransitions:
    def test_pending_cannot_accept(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.PENDING, OrderAction.ACCEPT_BY_USER)

    def test_pending_cannot_approve(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.PENDING, OrderAction.APPROVE_BY_ORG)

    def test_offered_cannot_approve(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.OFFERED, OrderAction.APPROVE_BY_ORG)

    def test_confirmed_cannot_offer(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.CONFIRMED, OrderAction.OFFER_BY_ORG)

    def test_active_cannot_offer(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.ACTIVE, OrderAction.OFFER_BY_ORG)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_order_state_machine.py -v`
Expected: Multiple failures (new actions/statuses don't exist in transition table yet)

- [ ] **Step 3: Rewrite state machine implementation**

Replace `app/orders/state_machine.py` entirely:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_order_state_machine.py -v`
Expected: All pass

- [ ] **Step 5: Run ruff and mypy**

Run: `task ruff:fix && task mypy`
Expected: State machine and tests pass. Other files may error due to removed enum values — expected.

- [ ] **Step 6: Commit**

```bash
git add app/orders/state_machine.py tests/unit/test_order_state_machine.py
git commit -m "refactor(orders): rewrite state machine for lifecycle v2"
```

---

## Task 3: Reservation Model & Service

**Files:**
- Create: `app/reservations/__init__.py`
- Create: `app/reservations/models.py`
- Create: `app/reservations/schemas.py`
- Create: `app/reservations/service.py`
- Modify: `app/core/database.py`

- [ ] **Step 1: Write reservation DB tests**

Create `tests/db/test_reservations.py`:

```python
from datetime import date

import pytest

from app.core.exceptions import AppValidationError
from app.reservations import service as reservation_service
from app.reservations.models import Reservation


@pytest.fixture
async def listing_id(client, verified_org, seed_categories):
    """Create a published listing and return its ID."""
    org_data, org_token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/listings/",
        json={
            "name": "Test Listing",
            "category_id": category_id,
            "price": 1000.00,
        },
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert resp.status_code == 201
    listing_id: str = resp.json()["id"]

    await client.patch(
        f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
        json={"status": "published"},
        headers={"Authorization": f"Bearer {org_token}"},
    )
    return listing_id


class TestCreateReservation:
    async def test_creates_reservation(self, listing_id: str) -> None:
        reservation = await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        assert reservation.listing_id == listing_id
        assert reservation.order_id == "ORD001"
        assert reservation.start_date == date(2026, 5, 1)
        assert reservation.end_date == date(2026, 5, 10)

    async def test_rejects_overlapping_dates(self, listing_id: str) -> None:
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        with pytest.raises(AppValidationError, match="overlapping reservation"):
            await reservation_service.create_reservation(
                listing_id=listing_id,
                order_id="ORD002",
                start_date=date(2026, 5, 5),
                end_date=date(2026, 5, 15),
            )

    async def test_allows_adjacent_dates(self, listing_id: str) -> None:
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        reservation = await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD002",
            start_date=date(2026, 5, 11),
            end_date=date(2026, 5, 20),
        )
        assert reservation.order_id == "ORD002"

    async def test_allows_same_dates_different_listing(self, listing_id: str, client, verified_org, seed_categories) -> None:
        org_data, org_token = verified_org
        org_id = org_data["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Other Listing", "category_id": seed_categories[0].id, "price": 2000.00},
            headers={"Authorization": f"Bearer {org_token}"},
        )
        other_listing_id: str = resp.json()["id"]

        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        reservation = await reservation_service.create_reservation(
            listing_id=other_listing_id,
            order_id="ORD002",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        assert reservation.listing_id == other_listing_id


class TestDeleteReservation:
    async def test_deletes_by_order_id(self, listing_id: str) -> None:
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        deleted = await reservation_service.delete_reservation_by_order("ORD001")
        assert deleted is True
        assert await Reservation.filter(order_id="ORD001").count() == 0

    async def test_delete_nonexistent_returns_false(self) -> None:
        deleted = await reservation_service.delete_reservation_by_order("NONEXIST")
        assert deleted is False


class TestListFutureReservations:
    async def test_returns_future_reservations(self, listing_id: str) -> None:
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD002",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 10),
        )
        results = await reservation_service.list_future_reservations(
            listing_id=listing_id,
            today=date(2026, 5, 5),
        )
        assert len(results) == 2

    async def test_excludes_past_reservations(self, listing_id: str) -> None:
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD001",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 10),
        )
        await reservation_service.create_reservation(
            listing_id=listing_id,
            order_id="ORD002",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 10),
        )
        results = await reservation_service.list_future_reservations(
            listing_id=listing_id,
            today=date(2026, 5, 5),
        )
        assert len(results) == 1
        assert results[0].order_id == "ORD002"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_reservations.py -v`
Expected: ImportError — module doesn't exist yet

- [ ] **Step 3: Create reservation package**

Create `app/reservations/__init__.py` (empty file).

Create `app/reservations/models.py`:

```python
from tortoise import fields
from tortoise.models import Model


class Reservation(Model):
    id = fields.UUIDField(primary_key=True)
    listing = fields.ForeignKeyField("models.Listing", related_name="reservations")
    listing_id: str
    order = fields.ForeignKeyField("models.Order", related_name="reservation", unique=True)
    order_id: str
    start_date = fields.DateField()
    end_date = fields.DateField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "reservations"
```

Create `app/reservations/schemas.py`:

```python
from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ReservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    listing_id: str
    start_date: date
    end_date: date
```

Create `app/reservations/service.py`:

```python
from datetime import UTC, date, datetime
from uuid import uuid4

from app.core.exceptions import AppValidationError
from app.reservations.models import Reservation


async def create_reservation(
    *,
    listing_id: str,
    order_id: str,
    start_date: date,
    end_date: date,
) -> Reservation:
    overlap_exists = await Reservation.filter(
        listing_id=listing_id,
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).exists()
    if overlap_exists:
        raise AppValidationError("Cannot approve: overlapping reservation exists for this listing")
    return await Reservation.create(
        id=uuid4(),
        listing_id=listing_id,
        order_id=order_id,
        start_date=start_date,
        end_date=end_date,
    )


async def delete_reservation_by_order(order_id: str) -> bool:
    deleted_count = await Reservation.filter(order_id=order_id).delete()
    return deleted_count > 0


async def list_future_reservations(
    *,
    listing_id: str,
    today: date | None = None,
) -> list[Reservation]:
    if today is None:
        today = datetime.now(UTC).date()
    return await Reservation.filter(
        listing_id=listing_id,
        end_date__gte=today,
    ).order_by("start_date")
```

- [ ] **Step 4: Register model in database config**

In `app/core/database.py`, add `"app.reservations.models"` to the `MODELS` list:

```python
MODELS = [
    "app.users.models",
    "app.organizations.models",
    "app.listings.models",
    "app.orders.models",
    "app.media.models",
    "app.chat.models",
    "app.reservations.models",
]
```

- [ ] **Step 5: Add reservations to test table list**

In `tests/conftest.py`, add `"reservations"` to `_TEST_TABLES` — it must come before `"orders"` due to FK dependency:

```python
_TEST_TABLES = (
    "chat_messages",
    "media",
    "reservations",
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

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/db/test_reservations.py -v`
Expected: All pass

- [ ] **Step 7: Run ruff and mypy**

Run: `task ruff:fix && task mypy`
Expected: Reservation module passes. Other files may still have errors from removed enums.

- [ ] **Step 8: Commit**

```bash
git add app/reservations/ app/core/database.py tests/conftest.py tests/db/test_reservations.py
git commit -m "feat(reservations): add Reservation model, service, and DB tests"
```

---

## Task 4: Reservation Router

**Files:**
- Create: `app/reservations/router.py`
- Modify: `app/main.py`
- Create: `tests/e2e/test_reservations.py`

- [ ] **Step 1: Write e2e tests for reservation endpoint**

Create `tests/e2e/test_reservations.py`:

```python
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.reservations.models import Reservation


def _future_date(days: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(days=days)).date().isoformat()


@pytest.fixture
async def listing_with_reservation(
    client: AsyncClient,
    create_listing: tuple[str, str, str],
) -> tuple[str, str, str]:
    """Create a listing with one reservation. Returns (listing_id, org_id, org_token)."""
    listing_id, org_id, org_token = create_listing
    start = (datetime.now(tz=UTC) + timedelta(days=5)).date()
    end = (datetime.now(tz=UTC) + timedelta(days=15)).date()
    await Reservation.create(
        listing_id=listing_id,
        order_id="FAKE01",
        start_date=start,
        end_date=end,
    )
    return listing_id, org_id, org_token


class TestListReservations:
    async def test_returns_future_reservations(
        self,
        client: AsyncClient,
        listing_with_reservation: tuple[str, str, str],
    ) -> None:
        listing_id, _, _ = listing_with_reservation
        resp = await client.get(f"/api/v1/listings/{listing_id}/reservations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "order_id" not in data[0]
        assert "listing_id" in data[0]
        assert "start_date" in data[0]
        assert "end_date" in data[0]

    async def test_excludes_past_reservations(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
    ) -> None:
        listing_id, _, _ = create_listing
        past_end = (datetime.now(tz=UTC) - timedelta(days=1)).date()
        past_start = (datetime.now(tz=UTC) - timedelta(days=10)).date()
        await Reservation.create(
            listing_id=listing_id,
            order_id="PAST01",
            start_date=past_start,
            end_date=past_end,
        )
        resp = await client.get(f"/api/v1/listings/{listing_id}/reservations")
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    async def test_no_auth_required(
        self,
        client: AsyncClient,
        listing_with_reservation: tuple[str, str, str],
    ) -> None:
        listing_id, _, _ = listing_with_reservation
        resp = await client.get(f"/api/v1/listings/{listing_id}/reservations")
        assert resp.status_code == 200

    async def test_empty_for_no_reservations(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
    ) -> None:
        listing_id, _, _ = create_listing
        resp = await client.get(f"/api/v1/listings/{listing_id}/reservations")
        assert resp.status_code == 200
        assert resp.json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/e2e/test_reservations.py -v`
Expected: 404 — router not registered yet

- [ ] **Step 3: Create reservation router**

Create `app/reservations/router.py`:

```python
from fastapi import APIRouter

from app.reservations import service
from app.reservations.schemas import ReservationRead

router = APIRouter(prefix="/api/v1", tags=["Reservations"])


@router.get("/listings/{listing_id}/reservations", response_model=list[ReservationRead])
async def list_listing_reservations(listing_id: str) -> list[ReservationRead]:
    reservations = await service.list_future_reservations(listing_id=listing_id)
    return [ReservationRead.model_validate(r) for r in reservations]
```

- [ ] **Step 4: Register router in main.py**

In `app/main.py`, add the import and include:

```python
from app.reservations.router import router as reservations_router
```

And in the router includes section:

```python
application.include_router(reservations_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/e2e/test_reservations.py -v`
Expected: All pass

- [ ] **Step 6: Run ruff and mypy**

Run: `task ruff:fix && task mypy`

- [ ] **Step 7: Commit**

```bash
git add app/reservations/router.py app/main.py tests/e2e/test_reservations.py
git commit -m "feat(reservations): add public calendar endpoint"
```

---

## Task 5: Rewrite Order Service & Router

**Files:**
- Modify: `app/orders/service.py`
- Modify: `app/orders/router.py`

- [ ] **Step 1: Rewrite order service**

Replace `app/orders/service.py` entirely:

```python
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import ListingStatus, OrderAction, OrderStatus, OrganizationStatus
from app.core.exceptions import AppValidationError, NotFoundError, PermissionDeniedError
from app.core.identifiers import create_with_short_id
from app.core.pagination import CursorParams, PaginatedResponse, paginate
from app.listings.models import Listing
from app.observability.events import emit_event
from app.observability.metrics import order_transitions, orders_created
from app.observability.tracing import traced
from app.orders.models import Order
from app.orders.schemas import OrderCreate, OrderOffer, OrderRead
from app.orders.state_machine import transition
from app.reservations import service as reservation_service
from app.users.models import User


def _record_transition(order_id: str, old_status: OrderStatus, new_status: OrderStatus) -> None:
    order_transitions.add(1, {"from_status": old_status.value, "to_status": new_status.value})
    emit_event("order.status_changed", order_id=order_id, old_status=old_status.value, new_status=new_status.value)


async def _schedule_expire_job(order: Order, expire_date: datetime) -> None:
    """Schedule a deferred ARQ job to expire the order at the given date."""
    from app.worker.settings import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job("expire_order", order.id, _defer_until=expire_date)


async def _schedule_activate_job(order: Order) -> None:
    """Schedule a deferred ARQ job to activate the order on offered_start_date."""
    from app.worker.settings import get_arq_pool

    if order.offered_start_date is None:
        return
    pool = await get_arq_pool()
    activate_at = datetime.combine(order.offered_start_date, datetime.min.time(), tzinfo=UTC)
    await pool.enqueue_job("activate_order", order.id, _defer_until=activate_at)


async def _schedule_finish_job(order: Order) -> None:
    """Schedule a deferred ARQ job to finish the order after offered_end_date."""
    from app.worker.settings import get_arq_pool

    if order.offered_end_date is None:
        return
    pool = await get_arq_pool()
    from datetime import timedelta

    finish_at = datetime.combine(order.offered_end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    await pool.enqueue_job("finish_order", order.id, _defer_until=finish_at)


@traced
async def create_order(user: User, data: OrderCreate) -> OrderRead:
    listing = await Listing.get_or_none(id=data.listing_id).select_related("organization")
    if listing is None:
        raise NotFoundError("Listing not found")

    if listing.status != ListingStatus.PUBLISHED:
        raise AppValidationError("Listing is not available for ordering")

    if listing.organization.status != OrganizationStatus.VERIFIED:
        raise PermissionDeniedError("Organization is not verified")

    if data.requested_start_date < datetime.now(UTC).date():
        raise AppValidationError("requested_start_date cannot be in the past")

    days = Decimal((data.requested_end_date - data.requested_start_date).days + 1)
    price = Decimal(str(listing.price))
    estimated_cost = (price * days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    order = await create_with_short_id(
        Order,
        listing=listing,
        organization=listing.organization,
        requester=user,
        requested_start_date=data.requested_start_date,
        requested_end_date=data.requested_end_date,
        estimated_cost=estimated_cost,
    )
    orders_created.add(1, {"org_id": listing.organization.id, "listing_id": data.listing_id})
    emit_event("order.created", order_id=order.id, listing_id=data.listing_id, user_id=user.id)

    expire_at = datetime.combine(data.requested_start_date, datetime.min.time(), tzinfo=UTC)
    await _schedule_expire_job(order, expire_at)

    return OrderRead.model_validate(order)


@traced
async def offer_order(order: Order, data: OrderOffer) -> OrderRead:
    old_status = order.status
    new_status = transition(order.status, OrderAction.OFFER_BY_ORG)
    order.status = new_status
    order.offered_cost = data.offered_cost
    order.offered_start_date = data.offered_start_date
    order.offered_end_date = data.offered_end_date
    await order.save()
    _record_transition(order.id, old_status, new_status)

    expire_at = datetime.combine(data.offered_start_date, datetime.min.time(), tzinfo=UTC)
    await _schedule_expire_job(order, expire_at)

    return OrderRead.model_validate(order)


@traced
async def accept_order(order: Order) -> OrderRead:
    old_status = order.status
    order.status = transition(order.status, OrderAction.ACCEPT_BY_USER)
    await order.save()
    _record_transition(order.id, old_status, order.status)
    return OrderRead.model_validate(order)


@traced
async def approve_order(order: Order) -> OrderRead:
    old_status = order.status
    order.status = transition(order.status, OrderAction.APPROVE_BY_ORG)

    if order.offered_start_date is None or order.offered_end_date is None:
        raise AppValidationError("Cannot approve order without offered dates")

    await reservation_service.create_reservation(
        listing_id=order.listing_id,
        order_id=order.id,
        start_date=order.offered_start_date,
        end_date=order.offered_end_date,
    )

    await order.save()
    _record_transition(order.id, old_status, order.status)

    await _schedule_activate_job(order)

    return OrderRead.model_validate(order)


async def _cancel_order(order: Order, action: OrderAction) -> OrderRead:
    old_status = order.status
    order.status = transition(order.status, action)
    await order.save()

    if old_status in (OrderStatus.CONFIRMED, OrderStatus.ACTIVE):
        await reservation_service.delete_reservation_by_order(order.id)

    _record_transition(order.id, old_status, order.status)
    return OrderRead.model_validate(order)


@traced
async def cancel_order_by_user(order: Order) -> OrderRead:
    return await _cancel_order(order, OrderAction.CANCEL_BY_USER)


@traced
async def cancel_order_by_org(order: Order) -> OrderRead:
    return await _cancel_order(order, OrderAction.CANCEL_BY_ORG)


@traced
async def get_order(order: Order) -> OrderRead:
    return OrderRead.model_validate(order)


@traced
async def list_user_orders(
    user: User,
    params: CursorParams,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(requester=user)
    if status:
        qs = qs.filter(status=status)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
    order_reads = [OrderRead.model_validate(order) for order in items]
    return PaginatedResponse(items=order_reads, next_cursor=next_cursor, has_more=has_more)


@traced
async def list_org_orders(
    org_id: str,
    params: CursorParams,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(organization_id=org_id)
    if status:
        qs = qs.filter(status=status)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
    order_reads = [OrderRead.model_validate(order) for order in items]
    return PaginatedResponse(items=order_reads, next_cursor=next_cursor, has_more=has_more)
```

- [ ] **Step 2: Rewrite order router**

Replace `app/orders/router.py` entirely:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies import require_active_user
from app.core.enums import OrderStatus
from app.core.pagination import CursorParams, PaginatedResponse
from app.orders import service
from app.orders.dependencies import get_org_order_or_404, require_order_requester
from app.orders.models import Order
from app.orders.schemas import OrderCreate, OrderOffer, OrderRead
from app.organizations.dependencies import require_org_editor
from app.organizations.models import Membership
from app.users.models import User

router = APIRouter(prefix="/api/v1", tags=["Orders"])


# --- User (renter) endpoints ---


@router.post("/orders/", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    user: Annotated[User, Depends(require_active_user)],
) -> OrderRead:
    return await service.create_order(user, data)


@router.get("/orders/", response_model=PaginatedResponse[OrderRead])
async def list_my_orders(
    user: Annotated[User, Depends(require_active_user)],
    cursor: str | None = None,
    limit: int = 20,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_user_orders(user, params, status=status)


@router.get("/orders/{order_id}", response_model=OrderRead)
async def get_my_order(
    order: Annotated[Order, Depends(require_order_requester)],
) -> OrderRead:
    return await service.get_order(order)


@router.patch("/orders/{order_id}/accept", response_model=OrderRead)
async def accept_order(
    order: Annotated[Order, Depends(require_order_requester)],
) -> OrderRead:
    return await service.accept_order(order)


@router.patch("/orders/{order_id}/cancel", response_model=OrderRead)
async def cancel_order_by_user(
    order: Annotated[Order, Depends(require_order_requester)],
) -> OrderRead:
    return await service.cancel_order_by_user(order)


# --- Organization (owner) endpoints ---


@router.get("/organizations/{org_id}/orders/", response_model=PaginatedResponse[OrderRead])
async def list_org_orders(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_editor)],
    cursor: str | None = None,
    limit: int = 20,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_org_orders(org_id, params, status=status)


@router.get("/organizations/{org_id}/orders/{order_id}", response_model=OrderRead)
async def get_org_order(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.get_order(order)


@router.patch("/organizations/{org_id}/orders/{order_id}/offer", response_model=OrderRead)
async def offer_order(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    data: OrderOffer,
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.offer_order(order, data)


@router.patch("/organizations/{org_id}/orders/{order_id}/approve", response_model=OrderRead)
async def approve_order(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.approve_order(order)


@router.patch("/organizations/{org_id}/orders/{order_id}/cancel", response_model=OrderRead)
async def cancel_order_by_org(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.cancel_order_by_org(order)
```

- [ ] **Step 3: Run ruff and mypy**

Run: `task ruff:fix && task mypy`
Fix any issues (likely import path issues since `app/worker/` doesn't exist yet — those will be resolved in Task 6).

- [ ] **Step 4: Commit**

```bash
git add app/orders/service.py app/orders/router.py
git commit -m "feat(orders): rewrite service and router for lifecycle v2"
```

---

## Task 6: Worker Module Restructure

**Files:**
- Create: `app/worker/__init__.py`
- Create: `app/worker/__main__.py`
- Create: `app/worker/settings.py`
- Create: `app/worker/media.py`
- Create: `app/worker/chat.py`
- Create: `app/worker/orders.py`
- Delete: `app/media/worker.py`
- Modify: `app/media/service.py` (import path)
- Modify: `app/chat/websocket.py` (import path)
- Modify: `Taskfile.yml`
- Modify: `docker-compose.prod.yml`

- [ ] **Step 1: Create `app/worker/__init__.py`**

Empty file.

- [ ] **Step 2: Create `app/worker/settings.py`**

```python
from typing import Any, ClassVar, cast

from arq import create_pool, func
from arq.connections import ArqRedis, RedisSettings
from arq.cron import cron
from arq.typing import WorkerCoroutine

from app.core.config import get_settings


async def get_arq_pool() -> ArqRedis:
    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.worker.redis_url)
    return await create_pool(redis_settings)


def _build_worker_settings() -> type:
    """Build WorkerSettings class with all functions and crons aggregated."""
    from app.worker.chat import notify_new_chat_message
    from app.worker.media import cleanup_orphans_cron, process_media_job
    from app.worker.orders import activate_order, expire_order, finish_order, order_sweep_cron

    class WorkerSettings:
        functions: ClassVar[list[Any]] = [
            func(cast("WorkerCoroutine", process_media_job), max_tries=3),
            func(cast("WorkerCoroutine", notify_new_chat_message), max_tries=1),
            func(cast("WorkerCoroutine", expire_order), max_tries=3),
            func(cast("WorkerCoroutine", activate_order), max_tries=3),
            func(cast("WorkerCoroutine", finish_order), max_tries=3),
        ]
        cron_jobs: ClassVar[list[Any]] = [
            cron(cast("WorkerCoroutine", cleanup_orphans_cron), minute={0}),
            cron(cast("WorkerCoroutine", order_sweep_cron), hour={3}, minute={0}),
        ]
        max_jobs = get_settings().worker.max_concurrent_jobs
        redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(get_settings().worker.redis_url)

    return WorkerSettings
```

- [ ] **Step 3: Create `app/worker/__main__.py`**

```python
import asyncio
from typing import cast

from arq.typing import WorkerSettingsBase
from arq.worker import create_worker

from app.worker.settings import _build_worker_settings


async def _main() -> None:
    cls = cast("type[WorkerSettingsBase]", _build_worker_settings())
    worker = create_worker(cls)
    await worker.main()


asyncio.run(_main())
```

- [ ] **Step 4: Create `app/worker/media.py`**

Move media job functions from `app/media/worker.py`. This file should contain: `_get_storage`, `_get_variant_specs`, `process_media_job`, `_process_photo`, `_process_video`, `_process_document`, `cleanup_orphans_cron`. Copy them verbatim from the current `app/media/worker.py` (lines 17-145), updating only the module-level imports as needed. The imports at the top:

```python
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.enums import MediaKind, MediaStatus
from app.media.models import Media
from app.media.processing import process_photo
from app.media.storage import StorageClient

logger = logging.getLogger(__name__)
```

Then all functions `_get_storage`, `_CONTEXT_TO_VARIANT_SET`, `_get_variant_specs`, `process_media_job`, `_process_photo`, `_process_video`, `_process_document`, `cleanup_orphans_cron` — copied verbatim from `app/media/worker.py`.

- [ ] **Step 5: Create `app/worker/chat.py`**

```python
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def notify_new_chat_message(_ctx: dict[Any, Any], order_id: str, message_id: str) -> None:
    """Stub for chat message notifications. Hook point for future push notifications."""
    logger.info("Chat notification: order=%s message=%s (stub — no notification sent)", order_id, message_id)
```

- [ ] **Step 6: Create `app/worker/orders.py`**

```python
import logging
from datetime import UTC, date, datetime
from typing import Any

from app.core.enums import OrderAction, OrderStatus
from app.core.exceptions import AppValidationError
from app.orders.models import Order
from app.orders.state_machine import transition
from app.reservations import service as reservation_service

logger = logging.getLogger(__name__)

_EXPIRABLE_STATUSES = {OrderStatus.PENDING, OrderStatus.OFFERED, OrderStatus.ACCEPTED}


async def _ensure_db() -> None:
    from tortoise import Tortoise

    from app.core.database import get_tortoise_config

    if not Tortoise._inited:
        await Tortoise.init(config=get_tortoise_config())


async def expire_order(_ctx: dict[str, Any], order_id: str) -> None:
    await _ensure_db()
    order = await Order.get_or_none(id=order_id)
    if order is None:
        logger.warning("expire_order: order %s not found", order_id)
        return
    if order.status not in _EXPIRABLE_STATUSES:
        logger.info("expire_order: order %s already in status %s, skipping", order_id, order.status.value)
        return
    try:
        old_status = order.status
        order.status = transition(order.status, OrderAction.EXPIRE)
        await order.save()
        logger.info("Expired order %s: %s → %s", order_id, old_status.value, order.status.value)
    except AppValidationError:
        logger.warning("expire_order: cannot expire order %s in status %s", order_id, order.status.value)


async def activate_order(_ctx: dict[str, Any], order_id: str) -> None:
    await _ensure_db()
    order = await Order.get_or_none(id=order_id)
    if order is None:
        logger.warning("activate_order: order %s not found", order_id)
        return
    if order.status != OrderStatus.CONFIRMED:
        logger.info("activate_order: order %s in status %s, skipping", order_id, order.status.value)
        return
    try:
        old_status = order.status
        order.status = transition(order.status, OrderAction.ACTIVATE)
        await order.save()
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


async def finish_order(_ctx: dict[str, Any], order_id: str) -> None:
    await _ensure_db()
    order = await Order.get_or_none(id=order_id)
    if order is None:
        logger.warning("finish_order: order %s not found", order_id)
        return
    if order.status != OrderStatus.ACTIVE:
        logger.info("finish_order: order %s in status %s, skipping", order_id, order.status.value)
        return
    try:
        old_status = order.status
        order.status = transition(order.status, OrderAction.FINISH)
        await order.save()
        logger.info("Finished order %s: %s → %s", order_id, old_status.value, order.status.value)
    except AppValidationError:
        logger.warning("finish_order: cannot finish order %s in status %s", order_id, order.status.value)


async def order_sweep_cron(_ctx: dict[Any, Any]) -> None:
    """Daily safety-net sweep for order auto-transitions."""
    await _ensure_db()
    today = datetime.now(UTC).date()

    # Expire stale orders
    expired_count = 0
    pending_stale = await Order.filter(status=OrderStatus.PENDING, requested_start_date__lt=today)
    for order in pending_stale:
        order.status = OrderStatus.EXPIRED
        await order.save()
        expired_count += 1

    offered_stale = await Order.filter(status=OrderStatus.OFFERED, offered_start_date__lt=today)
    for order in offered_stale:
        order.status = OrderStatus.EXPIRED
        await order.save()
        expired_count += 1

    accepted_stale = await Order.filter(status=OrderStatus.ACCEPTED, offered_start_date__lt=today)
    for order in accepted_stale:
        order.status = OrderStatus.EXPIRED
        await order.save()
        expired_count += 1

    # Activate confirmed orders
    activated_count = 0
    confirmed_ready = await Order.filter(status=OrderStatus.CONFIRMED, offered_start_date__lte=today)
    for order in confirmed_ready:
        order.status = OrderStatus.ACTIVE
        await order.save()
        activated_count += 1

    # Finish active orders
    finished_count = 0
    active_done = await Order.filter(status=OrderStatus.ACTIVE, offered_end_date__lt=today)
    for order in active_done:
        order.status = OrderStatus.FINISHED
        await order.save()
        finished_count += 1

    logger.info(
        "Order sweep: expired=%d, activated=%d, finished=%d",
        expired_count,
        activated_count,
        finished_count,
    )
```

- [ ] **Step 7: Delete `app/media/worker.py`**

Remove the file entirely.

- [ ] **Step 8: Update import paths in `app/media/service.py`**

In `app/media/service.py`, there are two places that import `get_arq_pool` from `app.media.worker`. Change both to:

```python
from app.worker.settings import get_arq_pool
```

- [ ] **Step 9: Update import path in `app/chat/websocket.py`**

Change the lazy import of `get_arq_pool` from `app.media.worker` to:

```python
from app.worker.settings import get_arq_pool
```

- [ ] **Step 10: Update Taskfile.yml**

Change `poetry run python -m app.media.worker` to `poetry run python -m app.worker` in the dev task.

- [ ] **Step 11: Update docker-compose.prod.yml**

Change the worker command from `python -m app.media.worker` to `python -m app.worker`.

- [ ] **Step 12: Run ruff and mypy**

Run: `task ruff:fix && task mypy`

- [ ] **Step 13: Commit**

```bash
git add app/worker/ app/media/service.py app/chat/websocket.py Taskfile.yml docker-compose.prod.yml
git rm app/media/worker.py
git commit -m "refactor(worker): extract into modular app/worker package with order jobs"
```

---

## Task 7: Fix Remaining References & Remove IN_RENT Logic

**Files:**
- Modify: `tests/db/conftest.py`
- Modify: `tests/db/test_worker.py`
- Modify: `tests/e2e/test_org_lifecycle.py`
- Modify: `tests/e2e/test_user_registration.py`
- Modify: `tests/e2e/test_listing_catalog.py`
- Modify: `tests/e2e/test_e2e_media.py`
- Modify: `tests/e2e/test_full_rental_journey.py`
- Modify: `tests/db/test_orders.py` (if exists)

- [ ] **Step 1: Update `tests/db/conftest.py`**

Change the `get_arq_pool` mock path from `app.media.worker.get_arq_pool` to `app.worker.settings.get_arq_pool`.

- [ ] **Step 2: Update `tests/db/test_worker.py`**

Change all imports from `app.media.worker` to `app.worker.media`. Specifically:
- `from app.media.worker import (...)` → `from app.worker.media import (...)`
- All `patch("app.media.worker._get_storage", ...)` → `patch("app.worker.media._get_storage", ...)`
- Check the `WorkerSettings` test — it now imports from `app.worker.settings`

- [ ] **Step 3: Update e2e test files**

In each of these files, replace `from app.media.worker import process_media_job` with `from app.worker.media import process_media_job`, and `patch("app.media.worker._get_storage", ...)` with `patch("app.worker.media._get_storage", ...)`:

- `tests/e2e/test_org_lifecycle.py`
- `tests/e2e/test_user_registration.py`
- `tests/e2e/test_listing_catalog.py`
- `tests/e2e/test_e2e_media.py`

- [ ] **Step 4: Update `tests/e2e/test_full_rental_journey.py`**

This file has `in_rent` assertions and the old lifecycle. Update:
- Change worker import paths
- Remove assertions that check `listing.status == ListingStatus.IN_RENT`
- Update any order lifecycle flow that uses `confirm` to use `accept` + `approve`
- Remove references to `REJECTED` and `DECLINED` statuses

Note: This is a large test file. Focus only on the lines that reference `IN_RENT`, `REJECTED`, `DECLINED`, `confirm`, `decline`, `reject`, and the worker import path. Don't rewrite unrelated parts.

- [ ] **Step 5: Check for and fix `tests/db/test_orders.py`**

Search for `in_rent` references and update them. Remove any tests that assert listing status changes to `in_rent`.

- [ ] **Step 6: Update `tests/conftest.py` — `create_order_for_chat` fixture**

The `create_order_for_chat` fixture creates an order in OFFERED status — this still works with the new lifecycle, so no change needed.

- [ ] **Step 7: Run full test suite**

Run: `task test`
Expected: All tests pass (except the order e2e tests which we'll rewrite in Tasks 8-9).

- [ ] **Step 8: Run ruff and mypy**

Run: `task ruff:fix && task mypy`

- [ ] **Step 9: Commit**

```bash
git add -u
git commit -m "fix: update all worker import paths and remove IN_RENT references"
```

---

## Task 8: Rewrite Order E2E Tests — Happy Path

**Files:**
- Modify: `tests/e2e/test_order_happy_path.py`

- [ ] **Step 1: Rewrite happy path e2e tests**

Replace `tests/e2e/test_order_happy_path.py` entirely:

```python
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.orders.models import Order
from app.reservations.models import Reservation


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _today() -> str:
    return datetime.now(tz=UTC).date().isoformat()


def _future_date(days: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(days=days)).date().isoformat()


async def _setup_order(
    client: AsyncClient,
    listing_id: str,
    renter_token: str,
    start_days: int = 2,
    end_days: int = 10,
) -> str:
    """Create a PENDING order and return its ID."""
    resp = await client.post(
        "/api/v1/orders/",
        json={
            "listing_id": listing_id,
            "requested_start_date": _future_date(start_days),
            "requested_end_date": _future_date(end_days),
        },
        headers=_auth(renter_token),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _offer_order(
    client: AsyncClient,
    org_id: str,
    order_id: str,
    org_token: str,
    start_days: int = 2,
    end_days: int = 10,
    cost: str = "5000.00",
) -> dict:
    resp = await client.patch(
        f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
        json={
            "offered_cost": cost,
            "offered_start_date": _future_date(start_days),
            "offered_end_date": _future_date(end_days),
        },
        headers=_auth(org_token),
    )
    assert resp.status_code == 200
    return resp.json()


async def _accept_order(client: AsyncClient, order_id: str, renter_token: str) -> dict:
    resp = await client.patch(
        f"/api/v1/orders/{order_id}/accept",
        headers=_auth(renter_token),
    )
    assert resp.status_code == 200
    return resp.json()


async def _approve_order(client: AsyncClient, org_id: str, order_id: str, org_token: str) -> dict:
    resp = await client.patch(
        f"/api/v1/organizations/{org_id}/orders/{order_id}/approve",
        headers=_auth(org_token),
    )
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.anyio
class TestOrderHappyPaths:
    async def test_full_lifecycle_pending_to_confirmed(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 1: PENDING → OFFERED → ACCEPTED → CONFIRMED (full negotiation)."""
        listing_id, org_id, org_token = create_listing

        # Create order
        order_id = await _setup_order(client, listing_id, renter_token)
        resp = await client.get(f"/api/v1/orders/{order_id}", headers=_auth(renter_token))
        assert resp.json()["status"] == "pending"

        # Org offers
        data = await _offer_order(client, org_id, order_id, org_token)
        assert data["status"] == "offered"

        # User accepts
        data = await _accept_order(client, order_id, renter_token)
        assert data["status"] == "accepted"

        # Org approves — creates reservation
        data = await _approve_order(client, org_id, order_id, org_token)
        assert data["status"] == "confirmed"

        # Verify reservation was created
        reservation = await Reservation.get_or_none(order_id=order_id)
        assert reservation is not None
        assert reservation.listing_id == listing_id

    async def test_reoffer_from_offered(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 2: Org re-offers with different terms."""
        listing_id, org_id, org_token = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)

        # First offer
        await _offer_order(client, org_id, order_id, org_token, cost="5000.00")

        # Re-offer with different terms
        data = await _offer_order(client, org_id, order_id, org_token, cost="4500.00")
        assert data["status"] == "offered"
        assert data["offered_cost"] == "4500.00"

    async def test_reoffer_from_accepted(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 3: Org re-offers after user already accepted (terms changed)."""
        listing_id, org_id, org_token = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)

        await _offer_order(client, org_id, order_id, org_token, cost="5000.00")
        await _accept_order(client, order_id, renter_token)

        # Org changes mind, re-offers
        data = await _offer_order(client, org_id, order_id, org_token, cost="6000.00")
        assert data["status"] == "offered"
        assert data["offered_cost"] == "6000.00"

    async def test_estimated_cost_calculation(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 4: Estimated cost = price × days."""
        listing_id, _, _ = create_listing
        # Listing price is 5000.00, requesting 5 days (days 2-6 inclusive = 5 days)
        order_id = await _setup_order(client, listing_id, renter_token, start_days=2, end_days=6)
        resp = await client.get(f"/api/v1/orders/{order_id}", headers=_auth(renter_token))
        assert resp.json()["estimated_cost"] == "25000.00"

    async def test_list_my_orders(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 5: List user's orders with status filter."""
        listing_id, org_id, org_token = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)
        await _offer_order(client, org_id, order_id, org_token)

        # All orders
        resp = await client.get("/api/v1/orders/", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

        # Filter by status
        resp = await client.get("/api/v1/orders/?status=offered", headers=_auth(renter_token))
        assert len(resp.json()["items"]) == 1

        resp = await client.get("/api/v1/orders/?status=pending", headers=_auth(renter_token))
        assert len(resp.json()["items"]) == 0

    async def test_list_org_orders(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Scenario 6: List organization's orders."""
        listing_id, org_id, org_token = create_listing
        await _setup_order(client, listing_id, renter_token)

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    async def test_approve_creates_reservation_blocks_overlap(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
        create_user,
    ) -> None:
        """Scenario 7: Approving one order blocks overlapping approval for another."""
        listing_id, org_id, org_token = create_listing

        # First order — full lifecycle to confirmed
        order1_id = await _setup_order(client, listing_id, renter_token, start_days=5, end_days=15)
        await _offer_order(client, org_id, order1_id, org_token, start_days=5, end_days=15)
        await _accept_order(client, order1_id, renter_token)
        await _approve_order(client, org_id, order1_id, org_token)

        # Second order with overlapping dates — different user
        _, renter2_token = await create_user(email="renter2@example.com", phone="+79002223344", name="R2", surname="T")
        order2_id = await _setup_order(client, listing_id, renter2_token, start_days=10, end_days=20)
        await _offer_order(client, org_id, order2_id, org_token, start_days=10, end_days=20)
        await _accept_order(client, order2_id, renter2_token)

        # Approve should fail due to overlap
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order2_id}/approve",
            headers=_auth(org_token),
        )
        assert resp.status_code == 400
        assert "overlapping" in resp.json()["detail"].lower()


@pytest.mark.anyio
class TestOrderNegativeCases:
    async def test_order_unpublished_listing(
        self,
        client: AsyncClient,
        verified_org: tuple[dict, str],
        seed_categories,
        renter_token: str,
    ) -> None:
        """Cannot order a hidden listing."""
        org_data, org_token = verified_org
        org_id = org_data["id"]
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Hidden", "category_id": seed_categories[0].id, "price": 100.00},
            headers=_auth(org_token),
        )
        listing_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": _future_date(1),
                "requested_end_date": _future_date(5),
            },
            headers=_auth(renter_token),
        )
        assert resp.status_code == 400

    async def test_order_past_start_date(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Cannot order with start date in the past."""
        listing_id, _, _ = create_listing
        yesterday = (datetime.now(tz=UTC) - timedelta(days=1)).date().isoformat()
        resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": yesterday,
                "requested_end_date": _future_date(5),
            },
            headers=_auth(renter_token),
        )
        assert resp.status_code == 400

    async def test_accept_from_wrong_status(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Cannot accept a PENDING order (must be OFFERED first)."""
        listing_id, _, _ = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)
        resp = await client.patch(f"/api/v1/orders/{order_id}/accept", headers=_auth(renter_token))
        assert resp.status_code == 400

    async def test_approve_from_wrong_status(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        """Cannot approve an OFFERED order (user must accept first)."""
        listing_id, org_id, org_token = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)
        await _offer_order(client, org_id, order_id, org_token)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/approve",
            headers=_auth(org_token),
        )
        assert resp.status_code == 400

    async def test_non_requester_cannot_accept(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
        create_user,
    ) -> None:
        """Another user cannot accept someone else's order."""
        listing_id, org_id, org_token = create_listing
        order_id = await _setup_order(client, listing_id, renter_token)
        await _offer_order(client, org_id, order_id, org_token)

        _, other_token = await create_user(email="other@example.com", phone="+79003334455", name="O", surname="T")
        resp = await client.patch(f"/api/v1/orders/{order_id}/accept", headers=_auth(other_token))
        assert resp.status_code == 403
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/e2e/test_order_happy_path.py -v`
Expected: All pass

- [ ] **Step 3: Run ruff and mypy**

Run: `task ruff:fix && task mypy`

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_order_happy_path.py
git commit -m "test(orders): rewrite happy path e2e tests for lifecycle v2"
```

---

## Task 9: Rewrite Order E2E Tests — Cancellations

**Files:**
- Modify: `tests/e2e/test_order_cancellations.py`

- [ ] **Step 1: Rewrite cancellation e2e tests**

Replace `tests/e2e/test_order_cancellations.py` entirely:

```python
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.orders.models import Order
from app.reservations.models import Reservation


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _future_date(days: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(days=days)).date().isoformat()


async def _create_pending_order(
    client: AsyncClient,
    listing_id: str,
    renter_token: str,
) -> str:
    resp = await client.post(
        "/api/v1/orders/",
        json={
            "listing_id": listing_id,
            "requested_start_date": _future_date(2),
            "requested_end_date": _future_date(10),
        },
        headers=_auth(renter_token),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _advance_to_offered(
    client: AsyncClient,
    org_id: str,
    order_id: str,
    org_token: str,
) -> None:
    resp = await client.patch(
        f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
        json={
            "offered_cost": "5000.00",
            "offered_start_date": _future_date(2),
            "offered_end_date": _future_date(10),
        },
        headers=_auth(org_token),
    )
    assert resp.status_code == 200


async def _advance_to_accepted(
    client: AsyncClient,
    org_id: str,
    order_id: str,
    org_token: str,
    renter_token: str,
) -> None:
    await _advance_to_offered(client, org_id, order_id, org_token)
    resp = await client.patch(f"/api/v1/orders/{order_id}/accept", headers=_auth(renter_token))
    assert resp.status_code == 200


async def _advance_to_confirmed(
    client: AsyncClient,
    org_id: str,
    order_id: str,
    org_token: str,
    renter_token: str,
) -> None:
    await _advance_to_accepted(client, org_id, order_id, org_token, renter_token)
    resp = await client.patch(
        f"/api/v1/organizations/{org_id}/orders/{order_id}/approve",
        headers=_auth(org_token),
    )
    assert resp.status_code == 200


@pytest.mark.anyio
class TestUserCancellations:
    async def test_cancel_pending(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, _, _ = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)

        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

    async def test_cancel_offered(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_offered(client, org_id, order_id, org_token)

        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

    async def test_cancel_accepted(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_accepted(client, org_id, order_id, org_token, renter_token)

        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

    async def test_cancel_confirmed_deletes_reservation(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_confirmed(client, org_id, order_id, org_token, renter_token)

        # Verify reservation exists
        assert await Reservation.filter(order_id=order_id).exists()

        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

        # Verify reservation was deleted
        assert not await Reservation.filter(order_id=order_id).exists()


@pytest.mark.anyio
class TestOrgCancellations:
    async def test_org_cancel_pending(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"

    async def test_org_cancel_offered(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_offered(client, org_id, order_id, org_token)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"

    async def test_org_cancel_accepted(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_accepted(client, org_id, order_id, org_token, renter_token)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"

    async def test_org_cancel_confirmed_deletes_reservation(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)
        await _advance_to_confirmed(client, org_id, order_id, org_token, renter_token)

        assert await Reservation.filter(order_id=order_id).exists()

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"
        assert not await Reservation.filter(order_id=order_id).exists()


@pytest.mark.anyio
class TestCancellationNegativeCases:
    async def test_cancel_terminal_order_fails(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str
    ) -> None:
        """Cannot cancel an already-canceled order."""
        listing_id, _, _ = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)

        # Cancel once
        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200

        # Try to cancel again
        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 400

    async def test_non_requester_cannot_cancel(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str, create_user
    ) -> None:
        listing_id, _, _ = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)

        _, other_token = await create_user(email="other@example.com", phone="+79003334455", name="O", surname="T")
        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(other_token))
        assert resp.status_code == 403

    async def test_wrong_org_cannot_cancel(
        self, client: AsyncClient, create_listing: tuple[str, str, str], renter_token: str, create_user
    ) -> None:
        """An org editor from a different org cannot cancel."""
        listing_id, org_id, _ = create_listing
        order_id = await _create_pending_order(client, listing_id, renter_token)

        # Use renter's token (not an org editor) — should get 403 or 404
        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(renter_token),
        )
        assert resp.status_code in (403, 404)
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/e2e/test_order_cancellations.py -v`
Expected: All pass

- [ ] **Step 3: Run ruff and mypy**

Run: `task ruff:fix && task mypy`

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_order_cancellations.py
git commit -m "test(orders): rewrite cancellation e2e tests for lifecycle v2"
```

---

## Task 10: Worker Order Job Tests

**Files:**
- Create: `tests/db/test_order_worker.py`

- [ ] **Step 1: Write tests for order worker jobs**

Create `tests/db/test_order_worker.py`:

```python
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.enums import OrderStatus
from app.orders.models import Order
from app.reservations.models import Reservation
from app.worker.orders import activate_order, expire_order, finish_order, order_sweep_cron


def _empty_ctx() -> dict:
    return {}


@pytest.fixture
async def pending_order(create_listing, renter_token, client) -> Order:
    """Create a PENDING order via API and return the ORM object."""
    listing_id, org_id, org_token = create_listing
    start = (datetime.now(tz=UTC) + timedelta(days=2)).date()
    end = (datetime.now(tz=UTC) + timedelta(days=10)).date()
    resp = await client.post(
        "/api/v1/orders/",
        json={
            "listing_id": listing_id,
            "requested_start_date": start.isoformat(),
            "requested_end_date": end.isoformat(),
        },
        headers={"Authorization": f"Bearer {renter_token}"},
    )
    assert resp.status_code == 201
    return await Order.get(id=resp.json()["id"])


class TestExpireOrder:
    async def test_expires_pending_order(self, pending_order: Order) -> None:
        # Simulate start date having passed by updating the date
        pending_order.requested_start_date = date(2026, 1, 1)
        await pending_order.save()

        await expire_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.EXPIRED

    async def test_skips_non_expirable_status(self, pending_order: Order) -> None:
        pending_order.status = OrderStatus.CONFIRMED
        await pending_order.save()

        await expire_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.CONFIRMED

    async def test_skips_missing_order(self) -> None:
        # Should not raise
        await expire_order(_empty_ctx(), "NONEXIST")


class TestActivateOrder:
    async def test_activates_confirmed_order(self, pending_order: Order) -> None:
        pending_order.status = OrderStatus.CONFIRMED
        pending_order.offered_start_date = date(2026, 1, 1)
        pending_order.offered_end_date = date(2026, 1, 10)
        await pending_order.save()

        await activate_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.ACTIVE

    async def test_skips_non_confirmed(self, pending_order: Order) -> None:
        await activate_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.PENDING


class TestFinishOrder:
    async def test_finishes_active_order(self, pending_order: Order) -> None:
        pending_order.status = OrderStatus.ACTIVE
        pending_order.offered_start_date = date(2026, 1, 1)
        pending_order.offered_end_date = date(2026, 1, 10)
        await pending_order.save()

        await finish_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.FINISHED

    async def test_skips_non_active(self, pending_order: Order) -> None:
        await finish_order(_empty_ctx(), pending_order.id)

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.PENDING


class TestOrderSweepCron:
    async def test_sweep_expires_stale_pending(self, pending_order: Order) -> None:
        pending_order.requested_start_date = date(2026, 1, 1)
        await pending_order.save()

        await order_sweep_cron(_empty_ctx())

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.EXPIRED

    async def test_sweep_activates_confirmed(self, pending_order: Order) -> None:
        pending_order.status = OrderStatus.CONFIRMED
        pending_order.offered_start_date = date(2026, 1, 1)
        pending_order.offered_end_date = date(2026, 12, 31)
        await pending_order.save()

        await order_sweep_cron(_empty_ctx())

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.ACTIVE

    async def test_sweep_finishes_active(self, pending_order: Order) -> None:
        pending_order.status = OrderStatus.ACTIVE
        pending_order.offered_start_date = date(2026, 1, 1)
        pending_order.offered_end_date = date(2026, 1, 10)
        await pending_order.save()

        await order_sweep_cron(_empty_ctx())

        order = await Order.get(id=pending_order.id)
        assert order.status == OrderStatus.FINISHED
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/db/test_order_worker.py -v`
Expected: All pass

- [ ] **Step 3: Run ruff and mypy**

Run: `task ruff:fix && task mypy`

- [ ] **Step 4: Commit**

```bash
git add tests/db/test_order_worker.py
git commit -m "test(worker): add tests for order background jobs and sweep"
```

---

## Task 11: Update Business Logic Docs & Final Verification

**Files:**
- Modify: `docs/business-logic.md`

- [ ] **Step 1: Update order lifecycle section in business-logic.md**

Update section 5 (Order Lifecycle) to reflect all changes:
- New state machine diagram (replace the old ASCII art)
- Update status descriptions: add ACCEPTED, EXPIRED; remove REJECTED, DECLINED
- Update transition rules: add accept, approve; remove confirm, decline, reject
- Add reservation model section
- Remove all `in_rent` references from the listing section
- Update API summary tables

- [ ] **Step 2: Update listing section — remove IN_RENT**

In the listing status section of business-logic.md, remove `in_rent` from the listing statuses. Update any text that references listing status changing due to orders.

- [ ] **Step 3: Run full CI suite**

Run: `task ci`
Expected: ruff + mypy + all tests pass

- [ ] **Step 4: Commit**

```bash
git add docs/business-logic.md
git commit -m "docs: update business-logic.md for order lifecycle v2"
```

- [ ] **Step 5: Run full test suite one final time**

Run: `task test`
Expected: All green

---

## Summary of Commits

| # | Message |
|---|---------|
| 1 | `refactor(enums): update OrderStatus, OrderAction, ListingStatus for lifecycle v2` |
| 2 | `refactor(orders): rewrite state machine for lifecycle v2` |
| 3 | `feat(reservations): add Reservation model, service, and DB tests` |
| 4 | `feat(reservations): add public calendar endpoint` |
| 5 | `feat(orders): rewrite service and router for lifecycle v2` |
| 6 | `refactor(worker): extract into modular app/worker package with order jobs` |
| 7 | `fix: update all worker import paths and remove IN_RENT references` |
| 8 | `test(orders): rewrite happy path e2e tests for lifecycle v2` |
| 9 | `test(orders): rewrite cancellation e2e tests for lifecycle v2` |
| 10 | `test(worker): add tests for order background jobs and sweep` |
| 11 | `docs: update business-logic.md for order lifecycle v2` |
