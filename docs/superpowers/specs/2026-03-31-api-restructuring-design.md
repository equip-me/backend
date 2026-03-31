# API Restructuring — Design Spec

## Overview

Restructure the rental platform API to add versioned prefixes, cursor-based pagination, new listing endpoints, logical router grouping, and targeted docstrings.

## 1. Cursor Pagination Utility

### Location

`app/core/pagination.py`

### Cursor Format

Base64-encoded JSON containing the sort boundary:

```json
{"updated_at": "2026-03-30T12:00:00", "id": "abc123"}
```

Two fields ensure stable ordering even when `updated_at` is identical across rows.

### Components

**`CursorParams`** — extracted from query params via `Depends`:

- `cursor: str | None = None` — opaque cursor from previous response
- `limit: int = 20` — capped at 100, minimum 1

**`PaginatedResponse[T]`** — generic response envelope:

```json
{
  "items": ["..."],
  "next_cursor": "base64...",
  "has_more": true
}
```

**`paginate(queryset, params, ordering=("-updated_at", "-id")) -> PaginatedResponse`**:

1. If `cursor` is provided, decode it and apply `WHERE (updated_at, id) < (:ts, :id)` (for descending order).
2. Apply `ORDER BY updated_at DESC, id DESC`.
3. Fetch `limit + 1` rows — if `limit + 1` rows returned, there are more pages; encode last included row as `next_cursor`.
4. Return `PaginatedResponse` with `items[:limit]`.

The `ordering` parameter allows per-endpoint override (e.g., `("-created_at", "-id")`). The cursor always encodes the fields matching the ordering tuple — so a `("-created_at", "-id")` endpoint produces cursors with `{"created_at": ..., "id": ...}` instead of `updated_at`.

### Endpoints that stay unpaginated

Small, bounded datasets — pagination adds no value:

- `GET /api/v1/listings/categories/`
- `GET /api/v1/organizations/{org_id}/listings/categories/`
- Organization contacts (sub-resource of a single org)

These continue to return bare arrays.

---

## 2. API Versioning & Router Structure

### Prefix

All routes move under `/api/v1/`. Applied in `main.py` via `include_router(prefix=...)`.

### Router map

| Router file | Prefix | Tag | Contains |
|---|---|---|---|
| `app/users/router.py` | `/api/v1/users` | `Users` | register, login, get/update me, get user by id |
| `app/organizations/router.py` | `/api/v1/organizations` | `Organizations` | CRUD, contacts, payment details, photo, public list |
| `app/organizations/members_router.py` | `/api/v1/organizations` | `Memberships` | invite, join, approve, accept, role change, remove, list |
| `app/listings/router.py` | `/api/v1` | `Listings` | public catalog, org listings, single listing, CRUD, status change |
| `app/listings/categories_router.py` | `/api/v1` | `Listing Categories` | public categories, org categories, create category |
| `app/orders/router.py` | `/api/v1` | `Orders` | all user + org order endpoints |
| `app/media/router.py` | `/api/v1/media` | `Media` | upload, confirm, status, delete, retry |
| `app/admin/router.py` | `/api/v1/private` | `Admin` | verify org, change user role, change privilege, list users |

### Key decisions

- **Memberships split out** from `organizations/router.py` — the org router has 20+ endpoints; memberships are a distinct concern.
- **Listings & categories split** — categories are a sub-resource with their own tag.
- **Admin router** — new `app/admin/` module consolidates all `/private/` routes. The new list-users endpoint lives here.
- **Auth stays in users router** — login and register are tightly coupled to the user entity; splitting for 2 endpoints adds no value.

### Route path migration

| Current | New |
|---|---|
| `POST /users/` | `POST /api/v1/users/` |
| `POST /users/token` | `POST /api/v1/users/token` |
| `GET /users/me` | `GET /api/v1/users/me` |
| `GET /listings/` | `GET /api/v1/listings/` |
| `GET /organizations/{id}` | `GET /api/v1/organizations/{id}` |
| `PATCH /private/users/{id}/role` | `PATCH /api/v1/private/users/{id}/role` |
| `PATCH /private/organizations/{id}/verify` | `PATCH /api/v1/private/organizations/{id}/verify` |

No path semantics change — just the `/api/v1` prefix and regrouping.

---

## 3. New & Modified Endpoints

### New endpoints

#### List users (admin)

`GET /api/v1/private/users/`

- **Auth:** Platform Admin
- **Query params:** `?search=...` (matches name, surname, email via `icontains`), `?role=...` (enum filter), `?cursor=...&limit=20`
- **Response:** `PaginatedResponse[UserRead]`
- **Ordering:** `-created_at, -id`

#### List organizations (public)

`GET /api/v1/organizations/`

- **Auth:** Public
- **Query params:** `?search=...` (matches `short_name`, `full_name` via `icontains`), `?cursor=...&limit=20`
- **Response:** `PaginatedResponse[OrganizationListRead]`
- **Constraints:** Only verified organizations
- **Ordering:** `-created_at, -id`

`OrganizationListRead` — lightweight schema: `id`, `short_name`, `full_name`, `inn`, `status`, `photo`, `published_listing_count`. Ordering by listing count is not used because cursor pagination doesn't work with computed sort keys that change between requests; the count is included as a display field only.

### Modified endpoints

| Endpoint | Added params | Response | Ordering |
|---|---|---|---|
| `GET /api/v1/listings/` | `?search=...` (name), `?category_id`, `?organization_id`, cursor | `PaginatedResponse[ListingRead]` | `-updated_at, -id` |
| `GET /api/v1/organizations/{org_id}/listings/` | cursor | `PaginatedResponse[ListingRead]` | `-updated_at, -id` |
| `GET /api/v1/orders/` | `?status=...`, cursor | `PaginatedResponse[OrderRead]` | `-updated_at, -id` |
| `GET /api/v1/organizations/{org_id}/orders/` | `?status=...`, cursor | `PaginatedResponse[OrderRead]` | `-updated_at, -id` |
| `GET /api/v1/users/me/organizations` | cursor | `PaginatedResponse[OrganizationRead]` | `-created_at, -id` (via membership) |
| `GET /api/v1/organizations/{org_id}/members` | cursor | `PaginatedResponse[MembershipRead]` | `-created_at, -id` |

---

## 4. Docstrings

### Criteria

Only non-obvious routes get docstrings — where path + method + tag don't tell the full story.

### Format

FastAPI renders the first line as the OpenAPI summary, the rest as description:

```python
@router.patch("/{order_id}/offer")
async def offer_order(...) -> OrderRead:
    """Offer or re-offer rental terms to the renter.

    Allowed from pending or offered status. Org Editor only.
    """
```

### Routes that get docstrings

**Admin routes:**

- `GET /api/v1/private/users/` — "List all platform users. Supports search by name/email and role filter. Platform Admin only."
- `PATCH /api/v1/private/users/{user_id}/role` — "Change user role (user/suspended). Platform Admin only."
- `PATCH /api/v1/private/users/{user_id}/privilege` — "Promote/demote platform admin. Platform Owner only."
- `PATCH /api/v1/private/organizations/{org_id}/verify` — "Verify organization, making its published listings visible in the public catalog. Platform Admin only."

**Non-obvious visibility rules:**

- `GET /api/v1/listings/` — "Browse published listings from verified organizations only."
- `GET /api/v1/listings/{listing_id}` — "Get listing detail. Returns 403 for listings from unverified organizations if the requester is not an org member."
- `GET /api/v1/organizations/` — "Browse verified organizations with published listing count."
- `GET /api/v1/organizations/{org_id}/listings/` — "List all listings for the organization regardless of status. Org members only."

**State-transition endpoints:**

- `PATCH .../offer` — "Offer or re-offer rental terms. Allowed from pending or offered status."
- `PATCH .../cancel` (both variants) — "Cancel a confirmed or active order. Returns listing to published status if it was in_rent."

---

## 5. File Change Summary

### New files

| File | Purpose |
|---|---|
| `app/core/pagination.py` | `CursorParams`, `PaginatedResponse[T]`, `paginate()` |
| `app/admin/__init__.py` | Admin module |
| `app/admin/router.py` | Admin routes: list users, change role, change privilege, verify org |
| `app/organizations/members_router.py` | Membership routes extracted from organizations router |
| `app/listings/categories_router.py` | Category routes extracted from listings router |

### Modified files

| File | Changes |
|---|---|
| `app/main.py` | Include routers with `/api/v1` prefix, add new routers |
| `app/users/router.py` | Remove `/private/` routes (moved to admin), add prefix/tags |
| `app/organizations/router.py` | Remove membership + admin routes, add prefix/tags, add public list endpoint |
| `app/organizations/schemas.py` | Add `OrganizationListRead` schema |
| `app/organizations/service.py` | Add `list_public_organizations()` |
| `app/listings/router.py` | Remove category routes, add search param, add prefix/tags, paginate |
| `app/listings/service.py` | Update list functions for pagination + search |
| `app/orders/router.py` | Add status filter, prefix/tags, paginate |
| `app/orders/service.py` | Update list functions for pagination + status filter |
| `app/media/router.py` | Add prefix (already has tags) |
| `app/users/service.py` | Add `list_users()` for admin endpoint |
| `docs/business-logic.md` | Update API summary tables with new paths and new endpoints |

### Not changed

- **Models** — no schema migrations needed
- **Business logic, state machine, permissions** — unchanged
- **Non-paginated endpoints** (categories, contacts) — stay as bare arrays
- **Media router** — no new endpoints, just prefix

### Test impact

- All integration tests need route path updates (`/users/` → `/api/v1/users/`)
- Paginated endpoints return `{items, next_cursor, has_more}` instead of bare arrays — tests asserting on response shape need updating
