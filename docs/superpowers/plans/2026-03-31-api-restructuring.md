# API Restructuring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the rental platform API with versioned prefixes (`/api/v1/`), cursor-based pagination, new listing endpoints, logical router grouping, and targeted docstrings.

**Architecture:** Generic cursor pagination utility in `app/core/pagination.py`. Routers split by domain with explicit prefixes and OpenAPI tags. Admin operations consolidated into a dedicated `app/admin/` module. All list endpoints return `PaginatedResponse` envelope with opaque base64 cursors.

**Tech Stack:** FastAPI, Tortoise ORM, Pydantic v2, pytest + httpx AsyncClient

**Spec deviation:** The design spec states "no schema migrations needed," but `Organization` model lacks `created_at` — required for cursor pagination ordering. Task 2 adds this field.

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `app/core/pagination.py` | `CursorParams`, `PaginatedResponse[T]`, `encode_cursor`, `decode_cursor`, `paginate()` |
| `app/admin/__init__.py` | Empty module init |
| `app/admin/router.py` | Admin routes: list users, change role, change privilege, verify org |
| `app/organizations/members_router.py` | Membership routes extracted from organizations router |
| `app/listings/categories_router.py` | Category routes extracted from listings router |
| `tests/unit/test_pagination.py` | Unit tests for cursor encode/decode, CursorParams validation |
| `tests/db/test_pagination.py` | Integration tests for `paginate()` against real DB |
| `tests/db/test_admin.py` | Tests for admin list users endpoint |

### Modified files

| File | Changes |
|---|---|
| `app/organizations/models.py` | Add `created_at` field |
| `app/main.py` | New router includes with `/api/v1` prefixes |
| `app/users/router.py` | Add prefix/tags, remove admin routes, add `GET /me/organizations` |
| `app/organizations/router.py` | Remove memberships + admin routes, add prefix/tags, add `GET /` public list |
| `app/organizations/schemas.py` | Add `OrganizationListRead` |
| `app/organizations/service.py` | Add `list_public_organizations()`, update existing list functions for pagination |
| `app/listings/router.py` | Remove categories, add prefix/tags, pagination + search param |
| `app/listings/service.py` | Update list functions for pagination + search |
| `app/listings/categories_router.py` | (new file — see above) |
| `app/orders/router.py` | Add prefix/tags, pagination + status filter |
| `app/orders/service.py` | Update list functions for pagination + status filter |
| `app/media/router.py` | Update prefix |
| `app/users/service.py` | Add `list_users()` for admin endpoint |
| `tests/conftest.py` | Add `/api/v1` prefix to all fixture URLs |
| `tests/db/*.py` | Add `/api/v1` prefix to all test URLs |
| `tests/e2e/*.py` | Add `/api/v1` prefix to all test URLs |
| `docs/business-logic.md` | Update API summary tables |

---

## Python Conventions (for subagents)

- **No `# type: ignore`** — fix the type error or restructure
- **No `from __future__ import annotations`** — Pydantic v2 and Tortoise need runtime types
- **Strict mypy** — every function fully typed, no implicit `Any`
- **Ruff** — line length 119, `select = ["ALL"]` with project ignores (see `pyproject.toml`)
- Async everywhere (Tortoise ORM is async-native)
- 6-char short string IDs on user-facing models; UUID on internal models
- Pydantic v2 schemas for request/response

---

## Task 1: Cursor Pagination Utility

**Files:**
- Create: `app/core/pagination.py`
- Test: `tests/unit/test_pagination.py`

- [ ] **Step 1: Write unit tests for cursor encode/decode and CursorParams**

Create `tests/unit/test_pagination.py`:

```python
import json
from base64 import b64decode, b64encode
from datetime import UTC, datetime

import pytest

from app.core.pagination import CursorParams, decode_cursor, encode_cursor


class TestCursorEncoding:
    def test_encode_decode_roundtrip(self) -> None:
        values = {"updated_at": datetime(2026, 3, 30, 12, 0, 0, tzinfo=UTC), "id": "ABC123"}
        cursor = encode_cursor(values)
        decoded = decode_cursor(cursor)
        assert decoded["updated_at"] == values["updated_at"]
        assert decoded["id"] == values["id"]

    def test_encode_produces_base64(self) -> None:
        values = {"updated_at": datetime(2026, 1, 1, tzinfo=UTC), "id": "X"}
        cursor = encode_cursor(values)
        raw = json.loads(b64decode(cursor).decode())
        assert "updated_at" in raw
        assert "id" in raw

    def test_decode_invalid_base64_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor("not-valid-base64!!!")

    def test_decode_invalid_json_raises(self) -> None:
        bad = b64encode(b"not json").decode()
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor(bad)


class TestCursorParams:
    def test_defaults(self) -> None:
        params = CursorParams()
        assert params.cursor is None
        assert params.limit == 20

    def test_limit_capped_at_100(self) -> None:
        with pytest.raises(ValueError):  # noqa: PT011
            CursorParams(limit=101)

    def test_limit_minimum_1(self) -> None:
        with pytest.raises(ValueError):  # noqa: PT011
            CursorParams(limit=0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/unit/test_pagination.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.pagination'`

- [ ] **Step 3: Implement pagination module**

Create `app/core/pagination.py`:

```python
import json
from base64 import b64decode, b64encode
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field
from tortoise.expressions import Q
from tortoise.queryset import QuerySet

T = TypeVar("T")


class CursorParams(BaseModel):
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


def encode_cursor(values: dict[str, Any]) -> str:
    """Encode cursor values as a base64 JSON string."""
    serialized: dict[str, Any] = {}
    for key, val in values.items():
        if isinstance(val, datetime):
            serialized[key] = val.isoformat()
        else:
            serialized[key] = val
    return b64encode(json.dumps(serialized).encode()).decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode a base64 JSON cursor string back to values."""
    try:
        raw = json.loads(b64decode(cursor).decode())
    except Exception as exc:
        msg = "Invalid cursor"
        raise ValueError(msg) from exc
    if not isinstance(raw, dict):
        msg = "Invalid cursor"
        raise ValueError(msg)
    result: dict[str, Any] = {}
    for key, val in raw.items():
        if isinstance(val, str):
            try:
                result[key] = datetime.fromisoformat(val)
            except ValueError:
                result[key] = val
        else:
            result[key] = val
    return result


def _parse_ordering(ordering: tuple[str, ...]) -> list[tuple[str, bool]]:
    """Parse ordering tuple into (field_name, is_descending) pairs."""
    parsed: list[tuple[str, bool]] = []
    for field in ordering:
        if field.startswith("-"):
            parsed.append((field[1:], True))
        else:
            parsed.append((field, False))
    return parsed


async def paginate(
    queryset: QuerySet[Any],
    params: CursorParams,
    ordering: tuple[str, ...] = ("-updated_at", "-id"),
) -> tuple[list[Any], str | None, bool]:
    """Apply cursor pagination to a queryset.

    Returns (items, next_cursor, has_more).
    The cursor encodes the fields from the ordering tuple.
    """
    parsed = _parse_ordering(ordering)

    if params.cursor is not None:
        cursor_data = decode_cursor(params.cursor)
        # Build compound WHERE for cursor position.
        # For 2-field ordering (f1 DESC, f2 DESC):
        #   WHERE f1 < v1 OR (f1 = v1 AND f2 < v2)
        filters = Q()
        for i, (field, desc) in enumerate(parsed):
            eq_conditions: dict[str, Any] = {}
            for j in range(i):
                prev_field, _ = parsed[j]
                eq_conditions[prev_field] = cursor_data[prev_field]
            op = "lt" if desc else "gt"
            eq_conditions[f"{field}__{op}"] = cursor_data[field]
            filters |= Q(**eq_conditions)
        queryset = queryset.filter(filters)

    queryset = queryset.order_by(*ordering)
    items: list[Any] = await queryset.limit(params.limit + 1)

    has_more = len(items) > params.limit
    if has_more:
        items = items[: params.limit]

    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        cursor_values: dict[str, Any] = {}
        for field, _ in parsed:
            cursor_values[field] = getattr(last, field)
        next_cursor = encode_cursor(cursor_values)

    return items, next_cursor, has_more
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `poetry run pytest tests/unit/test_pagination.py -v`
Expected: All PASS

- [ ] **Step 5: Write integration test for `paginate()` with real DB**

Create `tests/db/test_pagination.py`:

```python
from typing import Any

from app.core.pagination import CursorParams, paginate
from app.users.models import User


async def test_paginate_returns_first_page(create_user: Any) -> None:
    for i in range(5):
        await create_user(email=f"page{i}@example.com", phone=f"+7999000000{i}")

    items, next_cursor, has_more = await paginate(
        User.all(),
        CursorParams(limit=3),
        ordering=("-created_at", "-id"),
    )
    assert len(items) == 3
    assert has_more is True
    assert next_cursor is not None


async def test_paginate_second_page_uses_cursor(create_user: Any) -> None:
    for i in range(5):
        await create_user(email=f"cur{i}@example.com", phone=f"+7999100000{i}")

    items1, cursor1, _ = await paginate(
        User.all(),
        CursorParams(limit=3),
        ordering=("-created_at", "-id"),
    )
    assert cursor1 is not None

    items2, cursor2, has_more2 = await paginate(
        User.all(),
        CursorParams(cursor=cursor1, limit=3),
        ordering=("-created_at", "-id"),
    )
    assert len(items2) == 2
    assert has_more2 is False
    assert cursor2 is None

    all_ids = [u.id for u in items1] + [u.id for u in items2]
    assert len(all_ids) == len(set(all_ids)), "Pages must not overlap"


async def test_paginate_empty_queryset() -> None:
    items, cursor, has_more = await paginate(
        User.all(),
        CursorParams(limit=10),
        ordering=("-created_at", "-id"),
    )
    assert items == []
    assert cursor is None
    assert has_more is False


async def test_paginate_exact_page_size(create_user: Any) -> None:
    for i in range(3):
        await create_user(email=f"exact{i}@example.com", phone=f"+7999200000{i}")

    items, cursor, has_more = await paginate(
        User.all(),
        CursorParams(limit=3),
        ordering=("-created_at", "-id"),
    )
    assert len(items) == 3
    assert has_more is False
    assert cursor is None
```

- [ ] **Step 6: Run integration tests**

Run: `poetry run pytest tests/db/test_pagination.py -v`
Expected: All PASS

- [ ] **Step 7: Run lint + typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/core/pagination.py tests/unit/test_pagination.py tests/db/test_pagination.py
git commit -m "feat: add cursor-based pagination utility"
```

---

## Task 2: Add `created_at` to Organization Model

**Files:**
- Modify: `app/organizations/models.py:11` (Organization class)

**Note:** No migration files exist in this project. The app uses `generate_schemas=True` in the lifespan which auto-creates tables. Tests use `Tortoise.generate_schemas()`. Adding a field here will auto-apply in both environments. For production, run `task db:makemigrations` after this change.

- [ ] **Step 1: Add the field**

In `app/organizations/models.py`, add `created_at` to the `Organization` model after the `status` field:

```python
    status = fields.CharEnumField(OrganizationStatus, default=OrganizationStatus.CREATED, max_length=20)
    created_at = fields.DatetimeField(auto_now_add=True)
```

- [ ] **Step 2: Generate migration**

Run: `task db:makemigrations -- --name add_org_created_at`

- [ ] **Step 3: Run existing tests to verify nothing breaks**

Run: `poetry run pytest tests/db/test_organizations.py -v --timeout=60`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add app/organizations/models.py migrations/
git commit -m "feat: add created_at field to Organization model"
```

---

## Task 3: Router Restructuring + Versioned Prefix

This task splits routers, adds prefix/tags, and updates `main.py`. After this task, all existing tests will break due to URL changes — Task 4 fixes them.

**Files:**
- Create: `app/admin/__init__.py`, `app/admin/router.py`
- Create: `app/organizations/members_router.py`
- Create: `app/listings/categories_router.py`
- Modify: `app/users/router.py`
- Modify: `app/organizations/router.py`
- Modify: `app/listings/router.py`
- Modify: `app/orders/router.py`
- Modify: `app/media/router.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create admin module**

Create `app/admin/__init__.py` (empty file).

Create `app/admin/router.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import require_platform_admin, require_platform_owner
from app.core.enums import MediaOwnerType
from app.media import service as media_service
from app.media.storage import StorageClient, get_storage
from app.organizations import service as org_service
from app.organizations.schemas import OrganizationRead
from app.users import service as user_service
from app.users.models import User
from app.users.schemas import AdminRoleUpdate, PrivilegeUpdate, UserRead

router = APIRouter(prefix="/api/v1/private", tags=["Admin"])


@router.patch("/users/{user_id}/role", response_model=UserRead)
async def change_role(
    user_id: str,
    data: AdminRoleUpdate,
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    """Change user role (user/suspended). Platform Admin only."""
    user = await user_service.change_user_role(user_id, data)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read


@router.patch("/users/{user_id}/privilege", response_model=UserRead)
async def change_privilege(
    user_id: str,
    data: PrivilegeUpdate,
    _owner: Annotated[User, Depends(require_platform_owner)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    """Promote/demote platform admin. Platform Owner only."""
    user = await user_service.change_privilege(user_id, data)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read


@router.patch("/organizations/{org_id}/verify", response_model=OrganizationRead)
async def verify_organization(
    org_id: str,
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    """Verify organization, making its published listings visible in the public catalog. Platform Admin only."""
    org_read = await org_service.verify_organization(org_id)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return org_read
```

- [ ] **Step 2: Create members router**

Create `app/organizations/members_router.py` — extract all membership endpoints from `app/organizations/router.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.core.dependencies import require_active_user
from app.organizations import service
from app.organizations.dependencies import get_org_or_404, require_org_admin, require_org_member
from app.organizations.models import Membership, Organization
from app.organizations.schemas import (
    MembershipApprove,
    MembershipInvite,
    MembershipRead,
    MembershipRoleUpdate,
)
from app.users.models import User

router = APIRouter(prefix="/api/v1/organizations", tags=["Memberships"])


@router.post("/{org_id}/members/invite", response_model=MembershipRead)
async def invite_member(
    org_id: str,
    data: MembershipInvite,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.invite_member(org_id, data)


@router.post("/{org_id}/members/join", response_model=MembershipRead)
async def join_organization(
    user: Annotated[User, Depends(require_active_user)],
    org: Annotated[Organization, Depends(get_org_or_404)],
) -> MembershipRead:
    return await service.join_organization(org.id, user)


@router.patch("/{org_id}/members/{member_id}/approve", response_model=MembershipRead)
async def approve_candidate(
    org_id: str,
    member_id: str,
    data: MembershipApprove,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.approve_candidate(org_id, member_id, data)


@router.patch("/{org_id}/members/{member_id}/accept", response_model=MembershipRead)
async def accept_invitation(
    member_id: str,
    user: Annotated[User, Depends(require_active_user)],
    org: Annotated[Organization, Depends(get_org_or_404)],
) -> MembershipRead:
    return await service.accept_invitation(org.id, member_id, user)


@router.patch("/{org_id}/members/{member_id}/role", response_model=MembershipRead)
async def change_member_role(
    org_id: str,
    member_id: str,
    data: MembershipRoleUpdate,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.change_member_role(org_id, member_id, data)


@router.delete("/{org_id}/members/{member_id}", status_code=204)
async def remove_member(
    member_id: str,
    user: Annotated[User, Depends(require_active_user)],
    org: Annotated[Organization, Depends(get_org_or_404)],
) -> Response:
    await service.remove_member(org.id, member_id, user)
    return Response(status_code=204)


@router.get("/{org_id}/members", response_model=list[MembershipRead])
async def list_members(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
) -> list[MembershipRead]:
    return await service.list_members(org_id)
```

- [ ] **Step 3: Create categories router**

Create `app/listings/categories_router.py` — extract category endpoints from `app/listings/router.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends

from app.listings import service
from app.listings.schemas import ListingCategoryCreate, ListingCategoryRead
from app.organizations.dependencies import require_org_editor, require_org_member
from app.organizations.models import Membership, Organization
from app.users.models import User

router = APIRouter(prefix="/api/v1", tags=["Listing Categories"])


@router.get("/listings/categories/", response_model=list[ListingCategoryRead])
async def list_public_categories() -> list[ListingCategoryRead]:
    return await service.list_public_categories()


@router.get("/organizations/{org_id}/listings/categories/", response_model=list[ListingCategoryRead])
async def list_org_categories(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
) -> list[ListingCategoryRead]:
    return await service.list_org_categories(org_id)


@router.post(
    "/organizations/{org_id}/listings/categories/",
    response_model=ListingCategoryRead,
    status_code=201,
)
async def create_category(
    data: ListingCategoryCreate,
    membership: Annotated[Membership, Depends(require_org_editor)],
) -> ListingCategoryRead:
    await membership.fetch_related("organization", "user")
    org: Organization = membership.organization
    user: User = membership.user
    return await service.create_category(org, user, data)
```

- [ ] **Step 4: Rewrite users router**

Replace `app/users/router.py` with — removes admin routes (moved to admin router), adds prefix/tags, adds `GET /me/organizations` (moved from organizations router):

```python
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user
from app.core.enums import MediaOwnerType
from app.media import service as media_service
from app.media.storage import StorageClient, get_storage
from app.organizations import service as org_service
from app.organizations.schemas import OrganizationRead
from app.users import service
from app.users.models import User
from app.users.schemas import LoginRequest, TokenResponse, UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.post("/")
async def register(data: UserCreate) -> TokenResponse:
    return await service.register(data)


@router.post("/token")
async def login(data: LoginRequest) -> TokenResponse:
    return await service.authenticate(data.email, data.password)


@router.get("/me", response_model=UserRead)
async def get_me(
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read


@router.patch("/me", response_model=UserRead)
async def update_me(
    data: UserUpdate,
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    updated = await service.update_me(user, data, storage)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, updated.id, storage)
    user_read = UserRead.model_validate(updated)
    user_read.profile_photo = photo
    return user_read


@router.get("/me/organizations", response_model=list[OrganizationRead])
async def list_my_organizations(
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> list[OrganizationRead]:
    orgs = await org_service.list_user_organizations(user)
    for org_read in orgs:
        org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return orgs


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: str,
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    user = await service.get_by_id(user_id)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read
```

**Note:** `GET /me/organizations` moved here from organizations router. `GET /{user_id}` must come AFTER `/me` routes to avoid FastAPI treating "me" as a `user_id`.

- [ ] **Step 5: Rewrite organizations router**

Replace `app/organizations/router.py` with — removes membership and admin routes, adds prefix/tags:

```python
from typing import Annotated

from dadata import Dadata
from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user
from app.core.enums import MediaOwnerType
from app.media import service as media_service
from app.media.storage import StorageClient, get_storage
from app.organizations import service
from app.organizations.dependencies import get_dadata_client, require_org_admin, require_org_member
from app.organizations.models import Membership, Organization
from app.organizations.schemas import (
    ContactRead,
    ContactsReplace,
    OrganizationCreate,
    OrganizationPhotoUpdate,
    OrganizationRead,
    PaymentDetailsCreate,
    PaymentDetailsRead,
)
from app.users.models import User

router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])


@router.post("/", response_model=OrganizationRead)
async def create_organization(
    data: OrganizationCreate,
    user: Annotated[User, Depends(require_active_user)],
    dadata: Annotated[Dadata, Depends(get_dadata_client)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    org_read = await service.create_organization(data, user, dadata)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return org_read


@router.get("/{org_id}", response_model=OrganizationRead)
async def get_organization(
    org_id: str,
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    org_read = await service.get_organization(org_id)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return org_read


@router.patch("/{org_id}/photo", response_model=OrganizationRead)
async def update_org_photo(
    data: OrganizationPhotoUpdate,
    membership: Annotated[Membership, Depends(require_org_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    await membership.fetch_related("organization", "user")
    org: Organization = membership.organization
    user: User = membership.user
    await media_service.attach_profile_photo(
        data.photo_id,
        MediaOwnerType.ORGANIZATION,
        org.id,
        user,
        storage,
    )
    await org.fetch_related("contacts")
    org_read = OrganizationRead.model_validate(org)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org.id, storage)
    return org_read


@router.put("/{org_id}/contacts", response_model=list[ContactRead])
async def replace_contacts(
    org_id: str,
    data: ContactsReplace,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> list[ContactRead]:
    return await service.replace_contacts(org_id, data)


@router.get("/{org_id}/payment-details", response_model=PaymentDetailsRead)
async def get_payment_details(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
) -> PaymentDetailsRead:
    return await service.get_payment_details(org_id)


@router.post("/{org_id}/payment-details", response_model=PaymentDetailsRead)
async def create_payment_details(
    org_id: str,
    data: PaymentDetailsCreate,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> PaymentDetailsRead:
    return await service.upsert_payment_details(org_id, data)
```

- [ ] **Step 6: Rewrite listings router**

Replace `app/listings/router.py` with — removes category endpoints, adds prefix/tags:

```python
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.listings import service
from app.listings.dependencies import get_category_filter, get_org_filter, resolve_listing, resolve_public_listing
from app.listings.models import Listing
from app.listings.schemas import ListingCreate, ListingRead, ListingStatusUpdate, ListingUpdate
from app.media.storage import StorageClient, get_storage
from app.organizations.dependencies import require_org_editor, require_org_member
from app.organizations.models import Membership, Organization
from app.users.models import User

router = APIRouter(prefix="/api/v1", tags=["Listings"])


@router.post(
    "/organizations/{org_id}/listings/",
    response_model=ListingRead,
    status_code=201,
)
async def create_listing(
    data: ListingCreate,
    membership: Annotated[Membership, Depends(require_org_editor)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> ListingRead:
    await membership.fetch_related("organization", "user")
    org: Organization = membership.organization
    user: User = membership.user
    return await service.create_listing(org, user, data, storage)


@router.patch("/organizations/{org_id}/listings/{listing_id}", response_model=ListingRead)
async def update_listing(
    data: ListingUpdate,
    listing: Annotated[Listing, Depends(resolve_listing)],
    membership: Annotated[Membership, Depends(require_org_editor)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> ListingRead:
    await membership.fetch_related("organization", "user")
    org: Organization = membership.organization
    user: User = membership.user
    return await service.update_listing(listing, org, data, user, storage)


@router.delete("/organizations/{org_id}/listings/{listing_id}", status_code=204)
async def delete_listing(
    listing: Annotated[Listing, Depends(resolve_listing)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> Response:
    await service.delete_listing(listing, storage)
    return Response(status_code=204)


@router.patch(
    "/organizations/{org_id}/listings/{listing_id}/status",
    response_model=ListingRead,
)
async def change_listing_status(
    data: ListingStatusUpdate,
    listing: Annotated[Listing, Depends(resolve_listing)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> ListingRead:
    return await service.change_listing_status(listing, data.status, storage)


@router.get("/organizations/{org_id}/listings/", response_model=list[ListingRead])
async def list_org_listings(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> list[ListingRead]:
    """List all listings for the organization regardless of status. Org members only."""
    return await service.list_org_listings(org_id, storage)


@router.get("/listings/", response_model=list[ListingRead])
async def list_public_listings(
    category_id: Annotated[str | None, Depends(get_category_filter)],
    organization_id: Annotated[str | None, Depends(get_org_filter)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> list[ListingRead]:
    """Browse published listings from verified organizations only."""
    return await service.list_public_listings(storage, category_id, organization_id)


@router.get("/listings/{listing_id}", response_model=ListingRead)
async def get_listing(
    listing: Annotated[Listing, Depends(resolve_public_listing)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> ListingRead:
    """Get listing detail. Returns 403 for listings from unverified organizations if the requester is not an org member."""
    return await service.get_listing_read(listing, storage)
```

- [ ] **Step 7: Update orders router prefix/tags**

In `app/orders/router.py`, change the router initialization:

```python
router = APIRouter(prefix="/api/v1", tags=["Orders"])
```

Remove the `"/` prefix from all route paths is NOT needed here — orders already uses full paths like `/orders/` and `/organizations/{org_id}/orders/`.

- [ ] **Step 8: Update media router prefix**

In `app/media/router.py`, change the router initialization:

```python
router = APIRouter(prefix="/api/v1/media", tags=["Media"])
```

And update all route paths to remove the `/media` prefix:
- `"/media/upload-url"` → `"/upload-url"`
- `"/media/{media_id}/status"` → `"/{media_id}/status"`
- `"/media/{media_id}"` → `"/{media_id}"`
- `"/media/{media_id}/confirm"` → `"/{media_id}/confirm"`
- `"/media/{media_id}/retry"` → `"/{media_id}/retry"`

- [ ] **Step 9: Update main.py**

Replace `app/main.py` router includes:

```python
from app.admin.router import router as admin_router
from app.listings.categories_router import router as categories_router
from app.organizations.members_router import router as members_router

# ... in create_app():
    application.include_router(users_router)
    application.include_router(organizations_router)
    application.include_router(members_router)
    application.include_router(listings_router)
    application.include_router(categories_router)
    application.include_router(orders_router)
    application.include_router(media_router)
    application.include_router(admin_router)
```

Remove the old imports. Routers now carry their own prefixes — no `prefix=` arg needed on `include_router`.

- [ ] **Step 10: Run lint + typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS (tests will fail — URL paths changed; fixed in the next steps)

**Do NOT commit yet** — tests are broken until URLs are updated.

---

## Task 4: Update All Test URLs

**This task MUST be completed immediately after Task 3.** The combined result is committed at the end of this task.

Every test file that makes HTTP requests needs the `/api/v1` prefix added. This is a systematic find-and-replace.

**Files:**
- Modify: `tests/conftest.py`
- Modify: all files in `tests/db/`
- Modify: all files in `tests/e2e/`

- [ ] **Step 1: Update conftest.py**

In `tests/conftest.py`, apply these replacements (all instances in the file):

| Old | New |
|---|---|
| `"/users/"` | `"/api/v1/users/"` |
| `"/users/me"` | `"/api/v1/users/me"` |
| `"/organizations/"` | `"/api/v1/organizations/"` |
| `f"/organizations/{org_id}/listings/"` | `f"/api/v1/organizations/{org_id}/listings/"` |
| `f"/organizations/{org_id}/listings/{listing_id}/status"` | `f"/api/v1/organizations/{org_id}/listings/{listing_id}/status"` |

- [ ] **Step 2: Update db test files**

Apply URL prefix updates across all `tests/db/` files using global search-and-replace. The patterns:

For **all test files** in `tests/db/` and `tests/e2e/`:
- Any string starting with `"/users/` → prepend `/api/v1` → `"/api/v1/users/`
- Any string starting with `"/organizations/` → `"/api/v1/organizations/`
- Any string starting with `"/listings/` → `"/api/v1/listings/`
- Any string starting with `"/orders/` → `"/api/v1/orders/`
- Any string starting with `"/media/` → `"/api/v1/media/`
- Any string starting with `"/private/` → `"/api/v1/private/`
- Same for f-strings: `f"/users/` → `f"/api/v1/users/`, etc.
- **Also:** `f"/organizations/` → `f"/api/v1/organizations/` (used extensively in f-strings)

**Verification:** After replacement, grep for any route-like string missing the prefix:

Run: `grep -rn '"/users/' tests/ | grep -v api/v1`
Run: `grep -rn '"/organizations/' tests/ | grep -v api/v1`
Run: `grep -rn '"/listings/' tests/ | grep -v api/v1`
Run: `grep -rn '"/orders/' tests/ | grep -v api/v1`
Run: `grep -rn '"/media/' tests/ | grep -v api/v1`
Run: `grep -rn '"/private/' tests/ | grep -v api/v1`

All should return empty (no matches).

- [ ] **Step 3: Also update the `/users/me/organizations` path**

The endpoint `GET /users/me/organizations` moved from organizations router to users router. The URL stays the same (`/api/v1/users/me/organizations`), so no functional change needed in tests. Verify the path used in tests matches.

- [ ] **Step 4: Run full test suite**

Run: `task test`
Expected: All PASS

- [ ] **Step 5: Commit (Tasks 3 + 4 together)**

```bash
git add app/admin/ app/organizations/members_router.py app/listings/categories_router.py \
       app/users/router.py app/organizations/router.py app/listings/router.py \
       app/orders/router.py app/media/router.py app/main.py tests/
git commit -m "refactor: restructure routers with /api/v1 prefix, OpenAPI tags, and update tests"
```

---

## Task 5: Admin List Users Endpoint

**Files:**
- Modify: `app/users/service.py`
- Modify: `app/admin/router.py`
- Create: `tests/db/test_admin.py`

- [ ] **Step 1: Write failing tests**

Create `tests/db/test_admin.py`:

```python
from typing import Any

from httpx import AsyncClient

from app.core.enums import UserRole
from app.users.models import User


class TestListUsers:
    async def test_list_users_admin_success(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_user: Any,
    ) -> None:
        await create_user(email="user1@example.com")
        await create_user(email="user2@example.com", phone="+79001112233")
        _, admin_token = admin_user
        resp = await client.get(
            "/api/v1/private/users/",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "next_cursor" in body
        assert "has_more" in body
        # admin + 2 users + orgcreator (from admin_user fixture) = at least 3
        assert len(body["items"]) >= 3

    async def test_list_users_requires_admin(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token = await create_user(email="regular@example.com")
        resp = await client.get(
            "/api/v1/private/users/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_list_users_search(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_user: Any,
    ) -> None:
        await create_user(email="alice@example.com", name="Alice", surname="Smith")
        await create_user(email="bob@example.com", name="Bob", surname="Jones", phone="+79001112233")
        _, admin_token = admin_user
        resp = await client.get(
            "/api/v1/private/users/?search=Alice",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(u["name"] == "Alice" for u in items)
        assert not any(u["name"] == "Bob" for u in items)

    async def test_list_users_role_filter(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_user: Any,
    ) -> None:
        user_data, _ = await create_user(email="suspended@example.com")
        await User.filter(id=user_data["id"]).update(role=UserRole.SUSPENDED)
        _, admin_token = admin_user
        resp = await client.get(
            "/api/v1/private/users/?role=suspended",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(u["role"] == "suspended" for u in items)
        assert len(items) >= 1

    async def test_list_users_pagination(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_user: Any,
    ) -> None:
        for i in range(5):
            await create_user(email=f"pg{i}@example.com", phone=f"+7999000000{i}")
        _, admin_token = admin_user
        headers = {"Authorization": f"Bearer {admin_token}"}

        resp1 = await client.get("/api/v1/private/users/?limit=3", headers=headers)
        body1 = resp1.json()
        assert len(body1["items"]) == 3
        assert body1["has_more"] is True
        assert body1["next_cursor"] is not None

        resp2 = await client.get(
            f"/api/v1/private/users/?limit=3&cursor={body1['next_cursor']}",
            headers=headers,
        )
        body2 = resp2.json()
        assert len(body2["items"]) > 0

        ids1 = {u["id"] for u in body1["items"]}
        ids2 = {u["id"] for u in body2["items"]}
        assert ids1.isdisjoint(ids2), "Pages must not overlap"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/db/test_admin.py -v`
Expected: FAIL — 404 on `/api/v1/private/users/`

- [ ] **Step 3: Implement list_users service**

In `app/users/service.py`, add:

```python
from app.core.enums import MediaOwnerType, UserRole
from app.core.pagination import CursorParams, PaginatedResponse, encode_cursor, paginate
from app.media import service as media_service
from app.media.storage import StorageClient
from app.users.schemas import UserRead

# ... existing code ...

@traced
async def list_users(
    params: CursorParams,
    storage: StorageClient,
    search: str | None = None,
    role: UserRole | None = None,
) -> PaginatedResponse[UserRead]:
    qs = User.all()
    if search:
        qs = qs.filter(
            Q(name__icontains=search) | Q(surname__icontains=search) | Q(email__icontains=search),
        )
    if role:
        qs = qs.filter(role=role)

    items, next_cursor, has_more = await paginate(qs, params, ordering=("-created_at", "-id"))

    user_reads: list[UserRead] = []
    for user in items:
        photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
        user_read = UserRead.model_validate(user)
        user_read.profile_photo = photo
        user_reads.append(user_read)

    return PaginatedResponse(items=user_reads, next_cursor=next_cursor, has_more=has_more)
```

Add the necessary imports at the top of the file:

```python
from tortoise.expressions import Q

from app.core.pagination import CursorParams, PaginatedResponse, paginate
```

- [ ] **Step 4: Add list_users route to admin router**

In `app/admin/router.py`, add:

```python
from app.core.enums import UserRole
from app.core.pagination import CursorParams, PaginatedResponse
from app.users.schemas import UserRead


@router.get("/users/", response_model=PaginatedResponse[UserRead])
async def list_users(
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
    role: UserRole | None = None,
) -> PaginatedResponse[UserRead]:
    """List all platform users. Supports search by name/email and role filter. Platform Admin only."""
    params = CursorParams(cursor=cursor, limit=limit)
    return await user_service.list_users(params, storage, search=search, role=role)
```

**Important:** Place this route BEFORE the `/users/{user_id}/role` route to avoid FastAPI treating `""` as empty path matching.

- [ ] **Step 5: Run tests**

Run: `poetry run pytest tests/db/test_admin.py -v`
Expected: All PASS

- [ ] **Step 6: Run lint + typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/admin/router.py app/users/service.py tests/db/test_admin.py
git commit -m "feat(admin): add paginated list users endpoint with search and role filter"
```

---

## Task 6: Public Organizations Listing

**Files:**
- Modify: `app/organizations/schemas.py`
- Modify: `app/organizations/service.py`
- Modify: `app/organizations/router.py`
- Test: `tests/db/test_organizations.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/db/test_organizations.py`:

```python
class TestListPublicOrganizations:
    async def test_list_only_verified(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        create_organization: Any,
        create_user: Any,
    ) -> None:
        # verified_org fixture creates one verified org
        # create another unverified org
        _, unverified_token = await create_user(email="unver@example.com")
        await create_organization(token=unverified_token, inn="5001012345")

        resp = await client.get("/api/v1/organizations/")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        # Only the verified org should appear
        assert len(body["items"]) == 1
        assert body["items"][0]["status"] == "verified"

    async def test_list_with_published_listing_count(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[Any],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create and publish a listing
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Item", "category_id": seed_categories[0].id, "price": 100.0},
            headers=headers,
        )
        listing_id = create_resp.json()["id"]
        await client.patch(
            f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers=headers,
        )

        resp = await client.get("/api/v1/organizations/")
        body = resp.json()
        assert body["items"][0]["published_listing_count"] == 1

    async def test_list_search_by_name(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
    ) -> None:
        org_data, _ = verified_org
        short_name = org_data["short_name"]

        # Search with a substring of the org name
        search_term = short_name[:5] if short_name else "Рога"
        resp = await client.get(f"/api/v1/organizations/?search={search_term}")
        body = resp.json()
        assert len(body["items"]) >= 1

    async def test_list_search_no_results(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
    ) -> None:
        resp = await client.get("/api/v1/organizations/?search=ZZZNONEXISTENT")
        body = resp.json()
        assert len(body["items"]) == 0

    async def test_list_pagination(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.get("/api/v1/organizations/?limit=1")
        body = resp.json()
        assert "items" in body
        assert "next_cursor" in body
        assert "has_more" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/db/test_organizations.py::TestListPublicOrganizations -v`
Expected: FAIL — 405 Method Not Allowed (GET on `/api/v1/organizations/` hits POST route)

- [ ] **Step 3: Add OrganizationListRead schema**

In `app/organizations/schemas.py`, add:

```python
class OrganizationListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    inn: str
    short_name: str | None
    full_name: str | None
    status: OrganizationStatus
    photo: ProfilePhotoRead | None = None
    published_listing_count: int = 0
```

- [ ] **Step 4: Implement list_public_organizations service**

In `app/organizations/service.py`, add:

```python
from tortoise.expressions import Q
from tortoise.functions import Count

from app.core.enums import ListingStatus, OrganizationStatus
from app.core.pagination import CursorParams, PaginatedResponse, paginate
from app.organizations.schemas import OrganizationListRead


@traced
async def list_public_organizations(
    params: CursorParams,
    search: str | None = None,
) -> tuple[list[Organization], str | None, bool]:
    qs = Organization.filter(status=OrganizationStatus.VERIFIED)
    if search:
        qs = qs.filter(Q(short_name__icontains=search) | Q(full_name__icontains=search))

    return await paginate(qs, params, ordering=("-created_at", "-id"))
```

- [ ] **Step 5: Add the route**

In `app/organizations/router.py`, add BEFORE the `/{org_id}` route (to avoid path conflicts):

```python
from app.core.pagination import CursorParams, PaginatedResponse
from app.organizations.schemas import OrganizationListRead


@router.get("/", response_model=PaginatedResponse[OrganizationListRead])
async def list_organizations(
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
) -> PaginatedResponse[OrganizationListRead]:
    """Browse verified organizations with published listing count."""
    params = CursorParams(cursor=cursor, limit=limit)
    items, next_cursor, has_more = await service.list_public_organizations(params, search=search)

    org_reads: list[OrganizationListRead] = []
    for org in items:
        published_count = await Listing.filter(
            organization=org,
            status=ListingStatus.PUBLISHED,
        ).count()
        photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org.id, storage)
        org_read = OrganizationListRead(
            id=org.id,
            inn=org.inn,
            short_name=org.short_name,
            full_name=org.full_name,
            status=org.status,
            photo=photo,
            published_listing_count=published_count,
        )
        org_reads.append(org_read)

    return PaginatedResponse(items=org_reads, next_cursor=next_cursor, has_more=has_more)
```

Add the necessary imports:

```python
from app.core.enums import ListingStatus, MediaOwnerType
from app.core.pagination import CursorParams, PaginatedResponse
from app.listings.models import Listing
from app.organizations.schemas import OrganizationListRead
```

- [ ] **Step 6: Run tests**

Run: `poetry run pytest tests/db/test_organizations.py::TestListPublicOrganizations -v`
Expected: All PASS

- [ ] **Step 7: Run full test suite + lint + typecheck**

Run: `task ci`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/organizations/router.py app/organizations/service.py app/organizations/schemas.py \
       tests/db/test_organizations.py
git commit -m "feat(organizations): add public organizations listing with search and pagination"
```

---

## Task 7: Paginate Listings + Search

**Files:**
- Modify: `app/listings/service.py`
- Modify: `app/listings/router.py`
- Modify: `tests/db/test_listings.py`

- [ ] **Step 1: Update service functions**

In `app/listings/service.py`:

Replace `list_public_listings`:

```python
@traced
async def list_public_listings(
    storage: StorageClient,
    params: CursorParams,
    category_id: str | None = None,
    organization_id: str | None = None,
    search: str | None = None,
) -> PaginatedResponse[ListingRead]:
    qs = Listing.filter(
        status=ListingStatus.PUBLISHED,
        organization__status=OrganizationStatus.VERIFIED,
    )
    if category_id is not None:
        qs = qs.filter(category_id=category_id)
    if organization_id is not None:
        qs = qs.filter(organization_id=organization_id)
    if search:
        qs = qs.filter(name__icontains=search)

    items, next_cursor, has_more = await paginate(
        qs.prefetch_related("category"),
        params,
        ordering=("-updated_at", "-id"),
    )

    listing_reads = [await _listing_to_read(listing, storage) for listing in items]
    return PaginatedResponse(items=listing_reads, next_cursor=next_cursor, has_more=has_more)
```

Replace `list_org_listings`:

```python
@traced
async def list_org_listings(
    org_id: str,
    storage: StorageClient,
    params: CursorParams,
) -> PaginatedResponse[ListingRead]:
    qs = Listing.filter(organization_id=org_id).prefetch_related("category")
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
    listing_reads = [await _listing_to_read(listing, storage) for listing in items]
    return PaginatedResponse(items=listing_reads, next_cursor=next_cursor, has_more=has_more)
```

Add imports at the top:

```python
from app.core.pagination import CursorParams, PaginatedResponse, paginate
```

- [ ] **Step 2: Update router**

In `app/listings/router.py`, update `list_public_listings`:

```python
from app.core.pagination import CursorParams, PaginatedResponse


@router.get("/listings/", response_model=PaginatedResponse[ListingRead])
async def list_public_listings(
    category_id: Annotated[str | None, Depends(get_category_filter)],
    organization_id: Annotated[str | None, Depends(get_org_filter)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
) -> PaginatedResponse[ListingRead]:
    """Browse published listings from verified organizations only."""
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_public_listings(storage, params, category_id, organization_id, search)
```

Update `list_org_listings`:

```python
@router.get("/organizations/{org_id}/listings/", response_model=PaginatedResponse[ListingRead])
async def list_org_listings(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[ListingRead]:
    """List all listings for the organization regardless of status. Org members only."""
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_org_listings(org_id, storage, params)
```

- [ ] **Step 3: Update existing tests for new response shape**

In `tests/db/test_listings.py`, update assertions that check list responses:

`TestListOrgListings::test_list_org_listings_all_statuses`:
```python
        # Old: assert len(resp.json()) == 3
        assert len(resp.json()["items"]) == 3
```

`TestPublicListings::test_public_listings_only_published_verified`:
```python
        # Old: names = [item["name"] for item in body]
        names = [item["name"] for item in body["items"]]
```

`TestPublicListings::test_public_listings_filter_by_category`:
```python
        # Old: assert len(body) == 1
        #      assert body[0]["name"] == "Cat0"
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "Cat0"
```

`TestPublicListings::test_public_listings_filter_by_org`:
```python
        # Old: assert len(body) == 1
        #      assert body[0]["organization_id"] == org_id
        assert len(body["items"]) == 1
        assert body["items"][0]["organization_id"] == org_id
```

Also add a test for search:

```python
class TestPublicListingsSearch:
    async def test_search_by_name(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        headers = {"Authorization": f"Bearer {token}"}

        for name in ["Excavator CAT", "Crane Liebherr", "Bulldozer"]:
            create_resp = await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": name, "category_id": seed_categories[0].id, "price": 100.0},
                headers=headers,
            )
            lid = create_resp.json()["id"]
            await client.patch(
                f"/api/v1/organizations/{org_id}/listings/{lid}/status",
                json={"status": "published"},
                headers=headers,
            )

        resp = await client.get("/api/v1/listings/?search=Excavator")
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Excavator CAT"
```

- [ ] **Step 4: Run tests**

Run: `poetry run pytest tests/db/test_listings.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/listings/service.py app/listings/router.py tests/db/test_listings.py
git commit -m "feat(listings): add pagination and search to listing endpoints"
```

---

## Task 8: Paginate Orders + Status Filter

**Files:**
- Modify: `app/orders/service.py`
- Modify: `app/orders/router.py`
- Modify: `tests/db/test_orders.py`

- [ ] **Step 1: Update service functions**

In `app/orders/service.py`:

Replace `list_user_orders`:

```python
from app.core.pagination import CursorParams, PaginatedResponse, paginate


@traced
async def list_user_orders(
    user: User,
    params: CursorParams,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(requester=user).prefetch_related("listing")
    if status:
        qs = qs.filter(status=status)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
    order_reads = [await _to_read(order) for order in items]
    return PaginatedResponse(items=order_reads, next_cursor=next_cursor, has_more=has_more)
```

Replace `list_org_orders`:

```python
@traced
async def list_org_orders(
    org_id: str,
    params: CursorParams,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(organization_id=org_id).prefetch_related("listing")
    if status:
        qs = qs.filter(status=status)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
    order_reads = [await _to_read(order) for order in items]
    return PaginatedResponse(items=order_reads, next_cursor=next_cursor, has_more=has_more)
```

- [ ] **Step 2: Update router**

In `app/orders/router.py`:

```python
from app.core.enums import OrderStatus
from app.core.pagination import CursorParams, PaginatedResponse


@router.get("/orders/", response_model=PaginatedResponse[OrderRead])
async def list_my_orders(
    user: Annotated[User, Depends(require_active_user)],
    cursor: str | None = None,
    limit: int = 20,
    status: OrderStatus | None = None,
) -> PaginatedResponse[OrderRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_user_orders(user, params, status=status)


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
```

- [ ] **Step 3: Update existing tests + add status filter test**

In `tests/db/test_orders.py`, update `TestListOrders`:

```python
    async def test_list_user_orders(self, ...) -> None:
        # ...
        # Old: assert len(resp.json()) == 2
        assert len(resp.json()["items"]) == 2

    async def test_list_user_orders_empty(self, ...) -> None:
        # ...
        # Old: assert resp.json() == []
        assert resp.json()["items"] == []

    async def test_list_org_orders(self, ...) -> None:
        # ...
        # Old: assert len(resp.json()) == 1
        assert len(resp.json()["items"]) == 1
```

Add status filter test:

```python
    async def test_list_user_orders_filter_by_status(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        await _create_order(client, listing_id, renter_token)
        order2 = await _create_order(client, listing_id, renter_token, start_offset=10)

        # Offer and reject the second order
        start = _today() + timedelta(days=2)
        end = start + timedelta(days=5)
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order2['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )

        resp = await client.get(
            "/api/v1/orders/?status=pending",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(o["status"] == "pending" for o in items)
        assert len(items) == 1
```

- [ ] **Step 4: Run tests**

Run: `poetry run pytest tests/db/test_orders.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/orders/service.py app/orders/router.py tests/db/test_orders.py
git commit -m "feat(orders): add pagination and status filter to order list endpoints"
```

---

## Task 9: Paginate My Organizations + Members

**Files:**
- Modify: `app/organizations/service.py`
- Modify: `app/users/router.py` (my-orgs endpoint)
- Modify: `app/organizations/members_router.py`

- [ ] **Step 1: Update list_user_organizations service**

In `app/organizations/service.py`:

```python
from app.core.pagination import CursorParams, paginate


@traced
async def list_user_organizations(
    user: User,
    params: CursorParams,
) -> tuple[list[Organization], str | None, bool]:
    qs = Membership.filter(
        user=user,
        status=MembershipStatus.MEMBER,
    ).prefetch_related("organization__contacts")

    items, next_cursor, has_more = await paginate(qs, params, ordering=("-created_at", "-id"))
    orgs = [m.organization for m in items]
    return orgs, next_cursor, has_more
```

- [ ] **Step 2: Update my-orgs route in users router**

In `app/users/router.py`, update `list_my_organizations`:

```python
from app.core.pagination import CursorParams, PaginatedResponse


@router.get("/me/organizations", response_model=PaginatedResponse[OrganizationRead])
async def list_my_organizations(
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[OrganizationRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    orgs, next_cursor, has_more = await org_service.list_user_organizations(user, params)
    org_reads: list[OrganizationRead] = []
    for org_read in [OrganizationRead.model_validate(org) for org in orgs]:
        org_read.photo = await media_service.get_profile_photo(
            MediaOwnerType.ORGANIZATION, org_read.id, storage,
        )
        org_reads.append(org_read)
    return PaginatedResponse(items=org_reads, next_cursor=next_cursor, has_more=has_more)
```

- [ ] **Step 3: Update list_members service**

In `app/organizations/service.py`:

```python
@traced
async def list_members(
    org_id: str,
    params: CursorParams,
) -> PaginatedResponse[MembershipRead]:
    qs = Membership.filter(organization_id=org_id)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-created_at", "-id"))
    member_reads = [MembershipRead.model_validate(m) for m in items]
    return PaginatedResponse(items=member_reads, next_cursor=next_cursor, has_more=has_more)
```

- [ ] **Step 4: Update members router**

In `app/organizations/members_router.py`:

```python
from app.core.pagination import CursorParams, PaginatedResponse


@router.get("/{org_id}/members", response_model=PaginatedResponse[MembershipRead])
async def list_members(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[MembershipRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_members(org_id, params)
```

- [ ] **Step 5: Update affected tests**

Tests that assert on `list_my_organizations` or `list_members` response shape need updating to use `resp.json()["items"]`.

Search for `"/api/v1/users/me/organizations"` and `"/members"` in test files and update assertions.

- [ ] **Step 6: Run full test suite**

Run: `task test`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add app/organizations/service.py app/users/router.py app/organizations/members_router.py tests/
git commit -m "feat: paginate my-organizations and members list endpoints"
```

---

## Task 10: Docstrings

**Files:**
- Modify: `app/admin/router.py`
- Modify: `app/listings/router.py`
- Modify: `app/organizations/router.py`
- Modify: `app/orders/router.py`

- [ ] **Step 1: Add docstrings to order state-transition endpoints**

In `app/orders/router.py`:

```python
@router.patch("/organizations/{org_id}/orders/{order_id}/offer", response_model=OrderRead)
async def offer_order(...) -> OrderRead:
    """Offer or re-offer rental terms to the renter.

    Allowed from pending or offered status. Org Editor only.
    """

@router.patch("/orders/{order_id}/cancel", response_model=OrderRead)
async def cancel_order_by_user(...) -> OrderRead:
    """Cancel a confirmed or active order.

    Returns listing to published status if it was in_rent.
    """

@router.patch("/organizations/{org_id}/orders/{order_id}/cancel", response_model=OrderRead)
async def cancel_order_by_org(...) -> OrderRead:
    """Cancel a confirmed or active order.

    Returns listing to published status if it was in_rent. Org Editor only.
    """
```

The admin routes, listing routes, and organizations routes already received docstrings in Tasks 3-6. Verify that all routes from the spec's docstrings list (Section 4 of the design spec) have their docstrings.

- [ ] **Step 2: Run lint**

Run: `task lint:fix`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/orders/router.py app/admin/router.py app/listings/router.py app/organizations/router.py
git commit -m "docs: add docstrings to non-obvious API routes"
```

---

## Task 11: Update business-logic.md

**Files:**
- Modify: `docs/business-logic.md`

- [ ] **Step 1: Update all API summary tables**

In `docs/business-logic.md`, update every API summary table to use `/api/v1/` prefixed paths. Also add the two new endpoints:

**User API Summary (Section 2.6):** Add `/api/v1/` prefix to all paths. Add:

```markdown
| GET | `/api/v1/private/users/` | Platform Admin | List all users (paginated, searchable, role filter) |
```

**Organization API Summary (Section 3.7):** Add `/api/v1/` prefix. Add:

```markdown
| GET | `/api/v1/organizations/` | Public | List verified organizations with published listing count |
```

**Listing API Summary (Section 4.6):** Add `/api/v1/` prefix.

**Order API Summary (Section 5.6):** Add `/api/v1/` prefix.

**Media API Summary (Section 6.7):** Add `/api/v1/` prefix.

**Membership API (Section 3.2):** Add `/api/v1/` prefix.

- [ ] **Step 2: Commit**

```bash
git add docs/business-logic.md
git commit -m "docs: update business-logic.md API tables with /api/v1 prefix and new endpoints"
```

---

## Task 12: Final Verification

- [ ] **Step 1: Run full CI**

Run: `task ci`
Expected: lint PASS, typecheck PASS, test PASS

- [ ] **Step 2: Verify no old URLs remain in codebase**

Run:
```bash
grep -rn '"/users/' app/ tests/ --include='*.py' | grep -v api/v1 | grep -v '# '
grep -rn '"/organizations/' app/ tests/ --include='*.py' | grep -v api/v1 | grep -v '# '
grep -rn '"/listings/' app/ tests/ --include='*.py' | grep -v api/v1 | grep -v '# '
grep -rn '"/orders/' app/ tests/ --include='*.py' | grep -v api/v1 | grep -v '# '
grep -rn '"/private/' app/ tests/ --include='*.py' | grep -v api/v1 | grep -v '# '
grep -rn '"/media/' app/ tests/ --include='*.py' | grep -v api/v1 | grep -v '# '
```

Expected: No matches (all URLs have been migrated).

- [ ] **Step 3: Check OpenAPI docs render correctly**

Run: `task run` and open `http://localhost:8000/docs`
Verify: Routes are grouped by tags (Users, Organizations, Memberships, Listings, Listing Categories, Orders, Media, Admin).
