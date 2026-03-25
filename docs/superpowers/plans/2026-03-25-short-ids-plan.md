# Short URL-Friendly IDs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace UUID primary keys on user-facing models with 6-character uppercase alphanumeric strings, with retry-on-collision safety.

**Architecture:** New `app/core/identifiers.py` module provides `generate_short_id()` and `create_with_short_id()`. Five models switch from `UUIDField` to `CharField(max_length=6)`. Auth pipeline and API layer update from `UUID` to `str` types throughout.

**Tech Stack:** Python stdlib `secrets`, Tortoise ORM `CharField`, `tortoise.exceptions.IntegrityError`

**Spec:** `docs/superpowers/specs/2026-03-25-short-ids-design.md`

---

## File Map

### Create

| File | Responsibility |
|------|---------------|
| `app/core/identifiers.py` | `generate_short_id()`, `create_with_short_id()` retry helper |
| `tests/test_identifiers.py` | Unit + integration tests for ID generation and retry logic |

### Modify

| File | Change |
|------|--------|
| `app/core/exceptions.py` | Add `IDGenerationError` |
| `app/users/models.py:8` | `UUIDField` → `CharField(max_length=6)` |
| `app/organizations/models.py:10` | same (Organization only) |
| `app/listings/models.py:10,22` | same (ListingCategory + Listing) |
| `app/orders/models.py:10` | same (Order) |
| `app/core/security.py:24` | `subject: UUID` → `subject: str` |
| `app/core/dependencies.py:28` | Remove `UUID(subject)` cast |
| `app/users/schemas.py:94` | `id: UUID` → `id: str` |
| `app/users/service.py` | Use `create_with_short_id`, param types `UUID` → `str` |
| `app/users/router.py` | Path param types `UUID` → `str` |
| `tests/conftest.py` | Remove `UUID` import/cast, update fixtures |
| `tests/test_users.py` | Replace `uuid.uuid4()`, add ID format assertions |

---

## Task 1: `generate_short_id` — Pure Unit Tests + Implementation

**Files:**
- Create: `tests/test_identifiers.py`
- Create: `app/core/identifiers.py`

- [ ] **Step 1: Write failing tests for `generate_short_id`**

Create `tests/test_identifiers.py`:

```python
import re

from app.core.identifiers import SHORT_ID_ALPHABET, SHORT_ID_LENGTH, generate_short_id

_VALID_PATTERN = re.compile(r"^[A-Z0-9]+$")


def test_generate_short_id_default_length() -> None:
    result = generate_short_id()
    assert len(result) == SHORT_ID_LENGTH


def test_generate_short_id_custom_length() -> None:
    for length in (4, 8, 12):
        result = generate_short_id(length)
        assert len(result) == length


def test_generate_short_id_valid_characters() -> None:
    for _ in range(100):
        result = generate_short_id()
        assert _VALID_PATTERN.match(result), f"Invalid character in {result}"


def test_generate_short_id_uniqueness() -> None:
    ids = {generate_short_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_short_id_alphabet_is_uppercase_alphanumeric() -> None:
    assert SHORT_ID_ALPHABET == "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    assert len(SHORT_ID_ALPHABET) == 36
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_identifiers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.identifiers'`

- [ ] **Step 3: Implement `generate_short_id`**

Create `app/core/identifiers.py`:

```python
from __future__ import annotations

import secrets
import string
from typing import Any, TypeVar

from tortoise.exceptions import IntegrityError
from tortoise.models import Model

SHORT_ID_ALPHABET = string.ascii_uppercase + string.digits
SHORT_ID_LENGTH = 6

_M = TypeVar("_M", bound=Model)


def generate_short_id(length: int = SHORT_ID_LENGTH) -> str:
    return "".join(secrets.choice(SHORT_ID_ALPHABET) for _ in range(length))
```

(Only the `generate_short_id` function for now; `create_with_short_id` comes in Task 3.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_identifiers.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add app/core/identifiers.py tests/test_identifiers.py
git commit -m "feat: add generate_short_id utility with tests"
```

---

## Task 2: Update Models — `UUIDField` → `CharField`

**Files:**
- Modify: `app/users/models.py:8`
- Modify: `app/organizations/models.py:10`
- Modify: `app/listings/models.py:10,22`
- Modify: `app/orders/models.py:10`

- [ ] **Step 1: Update User model**

In `app/users/models.py`, change line 8:

```python
# Before
id = fields.UUIDField(primary_key=True)

# After
id = fields.CharField(max_length=6, primary_key=True, default=generate_short_id)
```

Add import at top:

```python
from app.core.identifiers import generate_short_id
```

- [ ] **Step 2: Update Organization model**

In `app/organizations/models.py`, change line 10 the same way. Add import. Only `Organization` changes — `OrganizationContact`, `PaymentDetails`, and `Membership` keep `UUIDField`.

- [ ] **Step 3: Update ListingCategory and Listing models**

In `app/listings/models.py`, change lines 10 and 22 the same way. Add import.

- [ ] **Step 4: Update Order model**

In `app/orders/models.py`, change line 10 the same way. Add import.

- [ ] **Step 5: Commit**

```bash
git add app/users/models.py app/organizations/models.py app/listings/models.py app/orders/models.py
git commit -m "feat: switch user-facing models to 6-char short ID primary keys"
```

---

## Task 3: `IDGenerationError` + `create_with_short_id` + Integration Tests

**Files:**
- Modify: `app/core/exceptions.py`
- Modify: `app/core/identifiers.py`
- Modify: `tests/test_identifiers.py`

- [ ] **Step 1: Add `IDGenerationError` to exceptions**

In `app/core/exceptions.py`, add after `AppValidationError`:

```python
class IDGenerationError(AppError):
    pass
```

Add to `_STATUS_MAP`:

```python
IDGenerationError: 500,
```

- [ ] **Step 2: Write failing tests for `create_with_short_id`**

Append to `tests/test_identifiers.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tortoise.exceptions import IntegrityError

from app.core.exceptions import IDGenerationError
from app.core.identifiers import create_with_short_id
from app.users.models import User


async def test_create_with_short_id_success() -> None:
    user = await create_with_short_id(
        User,
        email="short@example.com",
        hashed_password="fakehash",
        phone="+79991234567",
        name="Test",
        surname="User",
    )
    assert len(user.id) == 6
    assert isinstance(user.id, str)


async def test_create_with_short_id_retries_on_pk_collision() -> None:
    first = await create_with_short_id(
        User,
        email="first@example.com",
        hashed_password="fakehash",
        phone="+79991234567",
        name="First",
        surname="User",
    )
    with patch(
        "app.core.identifiers.generate_short_id",
        side_effect=[first.id, first.id, "ZZZZZZ"],
    ):
        second = await create_with_short_id(
            User,
            email="second@example.com",
            hashed_password="fakehash",
            phone="+79997654321",
            name="Second",
            surname="User",
        )
    assert second.id == "ZZZZZZ"


async def test_create_with_short_id_propagates_non_pk_error() -> None:
    await create_with_short_id(
        User,
        email="dup@example.com",
        hashed_password="fakehash",
        phone="+79991234567",
        name="First",
        surname="User",
    )
    with pytest.raises(IntegrityError):
        await create_with_short_id(
            User,
            email="dup@example.com",
            hashed_password="fakehash",
            phone="+79997654321",
            name="Second",
            surname="User",
        )


async def test_create_with_short_id_raises_after_max_retries() -> None:
    existing = await create_with_short_id(
        User,
        email="existing@example.com",
        hashed_password="fakehash",
        phone="+79991234567",
        name="Existing",
        surname="User",
    )
    with (
        patch(
            "app.core.identifiers.generate_short_id",
            return_value=existing.id,
        ),
        pytest.raises(IDGenerationError),
    ):
        await create_with_short_id(
            User,
            max_retries=3,
            email="another@example.com",
            hashed_password="fakehash",
            phone="+79997654321",
            name="Another",
            surname="User",
        )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `poetry run pytest tests/test_identifiers.py -v -k "create_with"`
Expected: FAIL — `ImportError: cannot import name 'create_with_short_id'`

- [ ] **Step 4: Implement `create_with_short_id`**

Add to `app/core/identifiers.py`:

```python
from app.core.exceptions import IDGenerationError


def _is_pk_collision(exc: IntegrityError, model_class: type[Model]) -> bool:
    table: str = model_class._meta.db_table  # type: ignore[attr-defined]
    return f"{table}_pkey" in str(exc)


async def create_with_short_id(
    model_class: type[_M],
    max_retries: int = 5,
    **kwargs: Any,
) -> _M:
    last_exc: IntegrityError | None = None
    for _ in range(max_retries):
        kwargs["id"] = generate_short_id()
        try:
            return await model_class.create(**kwargs)  # type: ignore[return-value]
        except IntegrityError as e:
            if _is_pk_collision(e, model_class):
                last_exc = e
                continue
            raise
    msg = f"Failed to generate unique ID for {model_class.__name__} after {max_retries} attempts"
    raise IDGenerationError(msg) from last_exc
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `poetry run pytest tests/test_identifiers.py -v`
Expected: 9 PASSED (5 unit + 4 integration)

- [ ] **Step 6: Commit**

```bash
git add app/core/exceptions.py app/core/identifiers.py tests/test_identifiers.py
git commit -m "feat: add create_with_short_id with retry logic and tests"
```

---

## Task 4: Update Security and Auth Dependencies

**Files:**
- Modify: `app/core/security.py:24`
- Modify: `app/core/dependencies.py:28`

- [ ] **Step 1: Update `create_access_token` signature**

In `app/core/security.py`, change:

```python
# Before (line 24)
def create_access_token(subject: UUID) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(days=settings.jwt.token_lifetime_days)
    payload = {"sub": str(subject), "exp": expire}

# After
def create_access_token(subject: str) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(days=settings.jwt.token_lifetime_days)
    payload = {"sub": subject, "exp": expire}
```

Remove `from uuid import UUID` import (if no longer used elsewhere in the file).

- [ ] **Step 2: Update `get_current_user` dependency**

In `app/core/dependencies.py`, change:

```python
# Before (line 28)
    user = await User.get_or_none(id=UUID(subject))

# After
    user = await User.get_or_none(id=subject)
```

Remove `from uuid import UUID` import.

- [ ] **Step 3: Commit**

```bash
git add app/core/security.py app/core/dependencies.py
git commit -m "refactor: update auth pipeline from UUID to str IDs"
```

---

## Task 5: Update Schemas, Service, and Router

**Files:**
- Modify: `app/users/schemas.py:94`
- Modify: `app/users/service.py`
- Modify: `app/users/router.py`

- [ ] **Step 1: Update `UserRead` schema**

In `app/users/schemas.py`:

```python
# Before (line 94)
    id: UUID

# After
    id: str
```

Remove `from uuid import UUID` from imports (line 4). It's only used for `id: UUID`.

- [ ] **Step 2: Update user service**

In `app/users/service.py`:

Change `register()` to use `create_with_short_id`:

```python
# Before (lines 19-26)
    user = await User.create(
        email=data.email,
        hashed_password=hash_password(data.password),
        phone=data.phone,
        name=data.name,
        surname=data.surname,
        middle_name=data.middle_name,
    )

# After
    user = await create_with_short_id(
        User,
        email=data.email,
        hashed_password=hash_password(data.password),
        phone=data.phone,
        name=data.name,
        surname=data.surname,
        middle_name=data.middle_name,
    )
```

Add import: `from app.core.identifiers import create_with_short_id`

Change parameter types in `get_by_id`, `change_user_role`, `change_privilege`:

```python
# Before
async def get_by_id(user_id: UUID) -> User:
async def change_user_role(user_id: UUID, data: AdminRoleUpdate) -> User:
async def change_privilege(user_id: UUID, data: PrivilegeUpdate) -> User:

# After
async def get_by_id(user_id: str) -> User:
async def change_user_role(user_id: str, data: AdminRoleUpdate) -> User:
async def change_privilege(user_id: str, data: PrivilegeUpdate) -> User:
```

Remove `from uuid import UUID` import.

- [ ] **Step 3: Update router path parameters**

In `app/users/router.py`, change all three route handlers:

```python
# Before
async def get_user(user_id: UUID) -> User:
async def change_role(user_id: UUID, ...) -> User:
async def change_privilege(user_id: UUID, ...) -> User:

# After
async def get_user(user_id: str) -> User:
async def change_role(user_id: str, ...) -> User:
async def change_privilege(user_id: str, ...) -> User:
```

Remove `from uuid import UUID` import.

- [ ] **Step 4: Commit**

```bash
git add app/users/schemas.py app/users/service.py app/users/router.py
git commit -m "refactor: update user API layer from UUID to short string IDs"
```

---

## Task 6: Update Existing Tests

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_users.py`

- [ ] **Step 1: Update `conftest.py`**

In `tests/conftest.py`:

Remove the `UUID` import (lines 14-15):

```python
# Before
if TYPE_CHECKING:
    from uuid import UUID

# After — remove these lines entirely
```

Remove the `UUID` type annotation from `admin_user` and `owner_user` fixtures:

```python
# Before (line 79)
    user_id: UUID = user_data["id"]

# After
    user_id = user_data["id"]
```

Same change at line 87.

- [ ] **Step 2: Update `test_users.py`**

Replace `uuid` import and usage (line 1, 244):

```python
# Before (line 1)
import uuid

# After — remove this import
```

```python
# Before (line 244)
async def test_get_user_not_found(client: AsyncClient) -> None:
    resp = await client.get(f"/users/{uuid.uuid4()}")
    assert resp.status_code == 404

# After
async def test_get_user_not_found(client: AsyncClient) -> None:
    resp = await client.get("/users/ZZZZZZ")
    assert resp.status_code == 404
```

- [ ] **Step 3: Add ID format assertion to registration test**

Add a new test to `tests/test_users.py`:

```python
import re

_SHORT_ID_PATTERN = re.compile(r"^[A-Z0-9]{6}$")


async def test_registered_user_has_short_id(client: AsyncClient, create_user: Any) -> None:
    user_data, _ = await create_user(email="shortid@example.com")
    assert _SHORT_ID_PATTERN.match(user_data["id"]), f"ID {user_data['id']} is not a valid short ID"
```

- [ ] **Step 4: Add test for expired token with short ID subject**

Update `test_get_me_expired_token` to use a short ID instead of a UUID string:

```python
# Before (line 220)
    expired_payload = {"sub": "00000000-0000-0000-0000-000000000000", "exp": 0}

# After
    expired_payload = {"sub": "AAAAAA", "exp": 0}
```

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_users.py
git commit -m "test: update test suite for short string IDs"
```

---

## Task 7: Lint, Typecheck, Full Test Suite

- [ ] **Step 1: Run lint and auto-fix**

Run: `task lint:fix`

- [ ] **Step 2: Run typecheck**

Run: `task typecheck`

Fix any mypy errors (likely `_meta` access needing `type: ignore`).

- [ ] **Step 3: Run full test suite**

Run: `task test`

Expected: ALL PASSED

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "chore: fix lint and type errors from short ID migration"
```

(Only if there were fixes needed. Skip if clean.)
