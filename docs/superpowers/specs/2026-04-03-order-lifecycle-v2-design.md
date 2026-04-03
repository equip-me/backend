# Order Lifecycle V2 — Design Spec

Redesign of the order lifecycle to fix logical gaps, add a reservation model, and replace lazy auto-transitions with background jobs.

## Problems With Current Design

1. **User can't cancel PENDING orders** — once placed, the user is stuck waiting for the org.
2. **Org can't withdraw OFFERED orders** — no way to retract an offer before the user responds.
3. **No expiration** — PENDING/OFFERED orders can sit forever with no timeout.
4. **Listing `in_rent` is a blunt flag** — only one order can be active per listing, no date-range awareness. No calendar visibility for users.
5. **Org has no final say on confirmation** — user confirms and the deal is locked. The org can't verify availability before committing.
6. **Lazy auto-transitions** — CONFIRMED→ACTIVE and ACTIVE→FINISHED only trigger on read. If nobody reads the order, the status and listing state go stale.
7. **Redundant terminal states** — REJECTED and DECLINED are semantically identical to CANCELED_BY_ORGANIZATION and CANCELED_BY_USER.

## New State Machine

### Statuses (9)

| Status | Description | Terminal |
|--------|-------------|----------|
| PENDING | User placed order, awaiting org response | No |
| OFFERED | Org proposed terms (cost, dates) | No |
| ACCEPTED | User accepted the offered terms, awaiting org approval | No |
| CONFIRMED | Org approved, reservation created | No |
| ACTIVE | Rental in progress (start date reached) | No |
| FINISHED | Rental completed (end date passed) | Yes |
| CANCELED_BY_USER | User canceled the order | Yes |
| CANCELED_BY_ORGANIZATION | Org canceled the order | Yes |
| EXPIRED | Start date passed without reaching CONFIRMED | Yes |

### Removed Statuses

- `REJECTED` — replaced by CANCELED_BY_ORGANIZATION
- `DECLINED` — replaced by CANCELED_BY_USER

### Actions (8)

| Action | Triggered by |
|--------|-------------|
| OFFER_BY_ORG | Org editor |
| ACCEPT_BY_USER | Requester |
| APPROVE_BY_ORG | Org editor |
| CANCEL_BY_USER | Requester |
| CANCEL_BY_ORG | Org editor |
| ACTIVATE | Background job |
| FINISH | Background job |
| EXPIRE | Background job |

### Removed Actions

- `REJECT_BY_ORG` — replaced by CANCEL_BY_ORG from PENDING
- `CONFIRM_BY_USER` — replaced by ACCEPT_BY_USER
- `DECLINE_BY_USER` — replaced by CANCEL_BY_USER from OFFERED

### Transition Table

```
(PENDING,   OFFER_BY_ORG)   → OFFERED
(PENDING,   CANCEL_BY_USER) → CANCELED_BY_USER
(PENDING,   CANCEL_BY_ORG)  → CANCELED_BY_ORGANIZATION
(PENDING,   EXPIRE)         → EXPIRED

(OFFERED,   OFFER_BY_ORG)   → OFFERED                    # re-offer
(OFFERED,   ACCEPT_BY_USER) → ACCEPTED
(OFFERED,   CANCEL_BY_USER) → CANCELED_BY_USER
(OFFERED,   CANCEL_BY_ORG)  → CANCELED_BY_ORGANIZATION
(OFFERED,   EXPIRE)         → EXPIRED

(ACCEPTED,  OFFER_BY_ORG)   → OFFERED                    # org re-offers from accepted
(ACCEPTED,  APPROVE_BY_ORG) → CONFIRMED
(ACCEPTED,  CANCEL_BY_USER) → CANCELED_BY_USER
(ACCEPTED,  CANCEL_BY_ORG)  → CANCELED_BY_ORGANIZATION
(ACCEPTED,  EXPIRE)         → EXPIRED

(CONFIRMED, ACTIVATE)       → ACTIVE
(CONFIRMED, CANCEL_BY_USER) → CANCELED_BY_USER
(CONFIRMED, CANCEL_BY_ORG)  → CANCELED_BY_ORGANIZATION

(ACTIVE,    FINISH)         → FINISHED
(ACTIVE,    CANCEL_BY_USER) → CANCELED_BY_USER
(ACTIVE,    CANCEL_BY_ORG)  → CANCELED_BY_ORGANIZATION
```

### Visual Diagram

```
PENDING
  ├──[org: offer]──────► OFFERED
  │                        ├──[org: re-offer]──► OFFERED
  │                        ├──[user: accept]──► ACCEPTED
  │                        │                      ├──[org: approve]──► CONFIRMED ──[auto]──► ACTIVE ──[auto]──► FINISHED
  │                        │                      ├──[org: re-offer]──► OFFERED
  │                        │                      ├──[org: cancel]──► CANCELED_BY_ORGANIZATION
  │                        │                      ├──[user: cancel]──► CANCELED_BY_USER
  │                        │                      └──[auto: start_date passes]──► EXPIRED
  │                        ├──[user: cancel]──► CANCELED_BY_USER
  │                        ├──[org: cancel]──► CANCELED_BY_ORGANIZATION
  │                        └──[auto: start_date passes]──► EXPIRED
  ├──[org: cancel]─────► CANCELED_BY_ORGANIZATION
  ├──[user: cancel]────► CANCELED_BY_USER
  └──[auto: start_date passes]──► EXPIRED
```

## Reservation Model

### Data Model

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | Internal model |
| listing | FK → Listing | required | The reserved listing |
| order | FK → Order | required, unique | One reservation per order |
| start_date | date | required | Copied from order's `offered_start_date` |
| end_date | date | required | Copied from order's `offered_end_date` |
| created_at | datetime | auto | |

### Lifecycle

- **Created** when order transitions to CONFIRMED (org approves).
- **Deleted** when order is canceled from CONFIRMED or ACTIVE.
- **Kept** when order reaches FINISHED — serves as historical record.

### Overlap Validation

On the `approve` action, before creating a reservation, check for existing reservations on the same listing with overlapping date ranges:

```
overlap = existing.start_date <= new.end_date AND existing.end_date >= new.start_date
```

If overlap exists, reject the approval with a validation error.

### Calendar Endpoint

`GET /api/v1/listings/{listing_id}/reservations` — returns reservations where `end_date >= today`.

Response schema:

```
ReservationRead:
  - id: UUID
  - listing_id: str
  - start_date: date
  - end_date: date
```

No `order_id` in the public response — other users don't need to know which order holds the reservation. Public endpoint, no auth required — users need this to pick available dates.

## Listing Status Changes

### Remove `IN_RENT`

The `in_rent` listing status is replaced entirely by the reservation model. Remaining listing statuses:

- `HIDDEN`
- `PUBLISHED`
- `ARCHIVED`

All listing status manipulation is removed from the order service. Order transitions no longer affect listing status.

## API Changes

### New Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| PATCH | `/api/v1/orders/{id}/accept` | Requester | Accept offered terms (OFFERED → ACCEPTED) |
| PATCH | `/api/v1/organizations/{org_id}/orders/{id}/approve` | Org Editor | Approve and create reservation (ACCEPTED → CONFIRMED) |
| GET | `/api/v1/listings/{listing_id}/reservations` | Public | Active/future reservations (end_date >= today) |

### Modified Endpoints

| Endpoint | Change |
|----------|--------|
| `PATCH /api/v1/orders/{id}/cancel` | Now allowed from PENDING, OFFERED, ACCEPTED, CONFIRMED, ACTIVE |
| `PATCH /api/v1/organizations/{org_id}/orders/{id}/cancel` | Now allowed from PENDING, OFFERED, ACCEPTED, CONFIRMED, ACTIVE |

### Removed Endpoints

| Endpoint | Reason |
|----------|--------|
| `PATCH /api/v1/orders/{id}/confirm` | Replaced by `/accept` |
| `PATCH /api/v1/orders/{id}/decline` | Redundant, covered by `/cancel` |
| `PATCH /api/v1/organizations/{org_id}/orders/{id}/reject` | Redundant, covered by `/cancel` |

## Background Worker

### Worker Module Restructure

Extract from `app/media/worker.py` into modular layout:

```
app/
  worker/
    __init__.py
    settings.py        # Shared WorkerSettings, redis pool, cron registry
    media.py           # process_media_job, cleanup_orphans_cron
    orders.py          # order targeted jobs + daily sweep
    chat.py            # notify_new_chat_message
```

`settings.py` aggregates all functions and cron jobs from all modules into a single `WorkerSettings` class. Entrypoint: `python -m app.worker`.

### Targeted Order Jobs

When an order transitions, enqueue a deferred ARQ job for the relevant date:

| Trigger | Scheduled job | Run at |
|---------|--------------|--------|
| Order created (PENDING) | `expire_order` | `requested_start_date` |
| Org offers (OFFERED) | `expire_order` | `offered_start_date` |
| User accepts (ACCEPTED) | — | Keep existing scheduled job |
| Org approves (CONFIRMED) | `activate_order` | `offered_start_date` |
| Order activated (ACTIVE) | `finish_order` | `offered_end_date + 1 day` |

Each job checks current status before acting — if the order was already canceled or transitioned, the job is a no-op. When an order is re-offered, the old scheduled job becomes stale and is harmlessly ignored at execution time.

### Daily Sweep (Safety Net)

- Runs once daily (e.g. 03:00), configurable via cron schedule.
- Catches anything the targeted jobs missed (worker downtime, failed jobs).
- Logic: expire stale orders, activate confirmed, finish active.

### Lazy Transition Removal

Remove `maybe_auto_transition()` and `_apply_auto_transition()` from the read path. All automatic transitions are handled exclusively by background jobs.

## Code Cleanup

### Removed

- `maybe_auto_transition`, `_apply_auto_transition` from state machine and service
- `reject_order`, `decline_order`, `confirm_order` service functions
- `/reject`, `/decline`, `/confirm` endpoints
- `IN_RENT` from `ListingStatus` enum
- `REJECTED`, `DECLINED` from `OrderStatus` enum
- `REJECT_BY_ORG`, `CONFIRM_BY_USER`, `DECLINE_BY_USER` from `OrderAction` enum
- All listing status manipulation from order service

### DB

- Drop all tables, create fresh with new schema. No data migration.

## Testing

### Unit Tests

- State machine: all valid transitions, all invalid transitions, terminal state immutability.

### DB Tests

- Reservation creation, overlap validation, cleanup on cancellation.

### E2E Tests

- **Happy path**: PENDING → OFFERED → ACCEPTED → CONFIRMED → ACTIVE → FINISHED
- **Cancellation**: from every non-terminal state, both user and org side
- **Expiration**: PENDING, OFFERED, ACCEPTED orders with passed start dates
- **Re-offer**: from OFFERED and from ACCEPTED
- **Reservation overlap**: approve fails when dates conflict with existing reservation
- **Reservation calendar**: returns only reservations with end_date >= today
- **Reservation cleanup**: reservation deleted on cancellation from CONFIRMED/ACTIVE
