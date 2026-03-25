# Short URL-Friendly IDs for User-Facing Models

## Problem

All models use `UUIDField(primary_key=True)`, producing 36-character IDs like `fe888dc6-4665-4fb8-82e5-98260a037382`. These appear in URLs (`/users/{id}`, `/organizations/{id}/...`, `/listings/{id}`, `/orders/{id}`) and are unnecessarily long and unreadable.

## Decision

Replace UUID primary keys on user-facing models with 6-character random uppercase alphanumeric strings (base36: `A-Z0-9`). Non-user-facing models keep UUIDs.

### Why 6 Characters

- **Alphabet**: 36 characters (`ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789`)
- **Keyspace**: 36^6 = ~2.18 billion unique IDs
- **Per-insert collision at 10M records**: 10M / 2.18B = 0.46% — handled by retry on `IntegrityError`
- **Probability of needing 2 retries**: 0.002% — negligible
- **Case-insensitive** — no `aBc` vs `ABC` confusion
- **Example IDs**: `7KQ2NF`, `XT9B4A`, `M3PL8W`

## Scope

### Models Getting Short IDs

| Model | File | Current |
|-------|------|---------|
| `User` | `app/users/models.py` | `UUIDField(pk=True)` → `CharField(max_length=6, pk=True, default=generate_short_id)` |
| `Organization` | `app/organizations/models.py` | same change |
| `Listing` | `app/listings/models.py` | same change |
| `ListingCategory` | `app/listings/models.py` | same change |
| `Order` | `app/orders/models.py` | same change |

### Models Keeping UUIDs (not user-facing)

- `Membership` — accessed through org context, not directly in URLs
- `OrganizationContact` — nested under organization
- `PaymentDetails` — nested under organization

## Design

### ID Generation Utility — `app/core/identifiers.py`

New module with two public symbols:

**`generate_short_id(length: int = 6) -> str`**

Generates a random uppercase alphanumeric string using `secrets.choice` from Python stdlib. No external dependencies.

**`create_with_short_id(model_class, max_retries: int = 5, **kwargs) -> Model`**

Async helper that wraps `Model.create()` with retry logic:
1. Generate a short ID
2. Call `model_class.create(id=generated_id, **kwargs)`
3. On `IntegrityError` from PK collision, regenerate ID and retry
4. After `max_retries` exhausted, raise `IDGenerationError`

Only catches PK-specific `IntegrityError`. Other integrity violations (e.g., duplicate email) propagate immediately. The function inspects the database error to distinguish PK collisions from other constraint violations.

### Model Changes

Each affected model changes one line:

```python
# Before
id = fields.UUIDField(primary_key=True)

# After
id = fields.CharField(max_length=6, primary_key=True, default=generate_short_id)
```

The `default=generate_short_id` provides IDs for direct `Model.create()` calls (e.g., in tests). The `create_with_short_id` helper adds retry safety for production service-layer code.

### Schema Changes — `app/users/schemas.py`

```python
# Before
id: UUID

# After
id: str
```

Applied to `UserRead` and future response schemas for Organization, Listing, ListingCategory, Order.

### Router Changes — `app/users/router.py`

```python
# Before
async def get_user(user_id: UUID) -> User:

# After
async def get_user(user_id: str) -> User:
```

All three routes with `{user_id}` path parameter change from `UUID` to `str`.

### Service Changes — `app/users/service.py`

- `register()`: use `create_with_short_id(User, ...)` instead of `User.create(...)`
- `get_by_id()`, `change_user_role()`, `change_privilege()`: parameter type `UUID` → `str`

### Security / Dependencies Changes

- `app/core/security.py`: `create_access_token(subject: UUID)` → `create_access_token(subject: str)` — remove `str()` wrapping since subject is already a string
- `app/core/dependencies.py`: remove `UUID(subject)` cast — pass `subject` string directly to `User.get_or_none(id=subject)`

### Migration

A new Aerich migration alters the `id` column from `uuid` to `varchar(6)` on affected tables, and updates foreign key columns that reference them (e.g., `Order.requester_id`, `Membership.user_id`, `Listing.organization_id`, etc.).

Since the database has no production data yet, the migration can drop and recreate columns if needed.

## Test Plan

### Unit Tests for `app/core/identifiers.py` — `tests/test_identifiers.py`

1. **`generate_short_id` returns correct length** — default 6, custom length
2. **`generate_short_id` uses only valid characters** — all chars in `A-Z0-9`
3. **`generate_short_id` produces unique values** — generate 1000, assert no duplicates
4. **`generate_short_id` with custom length** — verify different lengths work
5. **`create_with_short_id` succeeds on first attempt** — normal create, verify model has 6-char ID
6. **`create_with_short_id` retries on PK collision** — mock to force first N calls to raise `IntegrityError` on PK, verify eventual success
7. **`create_with_short_id` propagates non-PK IntegrityError** — e.g., duplicate email raises immediately without retry
8. **`create_with_short_id` raises after max retries exhausted** — mock to always collide, verify `IDGenerationError` after 5 attempts

### Updates to Existing Tests — `tests/test_users.py`, `tests/conftest.py`

9. **ID format in responses** — `UserRead.id` is a 6-char alphanumeric string (not UUID)
10. **Path parameters accept short IDs** — existing `GET /users/{user_id}` tests pass with short IDs
11. **Not-found with invalid ID** — `GET /users/ZZZZZZ` returns 404 (previously used `uuid.uuid4()`)
12. **JWT contains string subject** — token `sub` claim is 6-char string, auth flow works
13. **Fixtures updated** — `conftest.py` references `user_data["id"]` as `str` instead of `UUID`

### Integration Considerations

14. **Foreign keys resolve correctly** — models with FKs to short-ID models (Membership → User, Order → User, etc.) store and query the 6-char string FK correctly
15. **Concurrent creation** — multiple rapid creates don't fail (retry handles rare collisions)
