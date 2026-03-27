# Listings Business Logic — Design Spec

## Scope

Implement the Listing Catalog module: CRUD for listings and categories, manual status management, visibility rules. Order-driven status transitions (e.g., `in_rent` on order activation) are out of scope — the Order module will own those.

Source of truth for domain rules: `docs/business-logic.md` section 4.

## Architecture

Single router (`app/listings/router.py`), single service (`app/listings/service.py`), with schemas and dependencies in their own files. Follows the same patterns established by the Organizations module.

### Files to create

| File | Purpose |
|------|---------|
| `app/listings/schemas.py` | Pydantic v2 request/response models |
| `app/listings/dependencies.py` | Listing resolution and visibility enforcement |
| `app/listings/service.py` | Business logic |
| `app/listings/router.py` | FastAPI endpoints |
| `tests/test_listings.py` | Integration tests |

### Files to modify

| File | Change |
|------|--------|
| `app/main.py` | Register listings router |
| `tests/conftest.py` | Add listing/category factory fixtures |

### Existing files (no changes)

- `app/listings/models.py` — `Listing` and `ListingCategory` already defined
- `app/core/enums.py` — `ListingStatus` already defined

## Schemas

### ListingCategory

**`ListingCategoryCreate`** — request body for creating a category:
- `name: str`

**`ListingCategoryRead`** — response model:
- `id: str`
- `name: str`
- `verified: bool`
- `created_at: datetime`
- `listing_count: int` — annotated count of associated listings

### Listing

**`ListingCreate`** — request body:
- `name: str`
- `category_id: str`
- `price: float`
- `description: str | None = None`
- `specifications: dict[str, str] | None = None`
- `with_operator: bool = False`
- `on_owner_site: bool = False`
- `delivery: bool = False`
- `installation: bool = False`
- `setup: bool = False`

**`ListingUpdate`** — partial update (all fields optional):
- Same fields as `ListingCreate`, all `| None` with default `None`

**`ListingRead`** — response model:
- All model fields
- `category: ListingCategoryRead` (nested)
- `organization_id: str`
- `added_by_id: str`
- `model_config = ConfigDict(from_attributes=True)`

**`ListingStatusUpdate`** — request body for status change:
- `status: ListingStatus`

## Dependencies

### `resolve_listing(listing_id, org_id, membership)`

Used by org-scoped mutation endpoints (update, delete, status change). Fetches listing by ID, verifies it belongs to the given org. Raises `NotFoundError` if not found or wrong org. Reuses `require_org_editor` from organizations for auth.

### `resolve_public_listing(listing_id, user?)`

Used by `GET /listings/{id}`. Accepts an optional current user (token is not required on this endpoint — unauthenticated requests pass `None`). Fetches listing by ID with org prefetch. If the listing's organization is not verified: checks whether the user is a member of that org; if not (or if unauthenticated), raises `PermissionDeniedError` (403). If listing not found, raises `NotFoundError` (404).

Auth dependencies (`require_org_editor`, `require_org_member`) are reused from `app/organizations/dependencies.py`.

## Service Functions

### Listings

- **`create_listing(org, user, data)`** — Creates listing via `create_with_short_id`. Category must exist and must be either verified or belong to the same org. Returns `ListingRead`.
- **`update_listing(listing, data)`** — Partial update. Only fields present in request are written. If `category_id` is changed, same category validation applies.
- **`delete_listing(listing)`** — Hard delete.
- **`change_listing_status(listing, status)`** — Sets the new status directly. No state-machine validation; any `ListingStatus` value is allowed for org editors.
- **`list_org_listings(org_id)`** — All listings belonging to the org (any status), ordered by `-updated_at`. Prefetches category.
- **`list_public_listings(category_id?, org_id?)`** — Only listings with status `PUBLISHED` from organizations with status `VERIFIED`. Optional filters by `category_id` and `organization_id`. Ordered by `-updated_at`. Prefetches category.
- **`get_listing(listing_id)`** — Single listing fetch by ID with category and organization prefetch.

### Categories

- **`create_category(org, user, name)`** — Creates category scoped to the org with `verified=False`.
- **`list_public_categories()`** — Verified categories only, annotated with listing count (counting only `published` listings from `verified` orgs), ordered by listing count descending.
- **`list_org_categories(org_id)`** — Categories that have listings in this org, plus all verified categories. Annotated with listing count (scoped to this org), ordered by listing count descending.

## Router Endpoints

### Public endpoints

| Method | Path | Response | Description |
|--------|------|----------|-------------|
| `GET` | `/listings/` | `list[ListingRead]` | Browse published listings from verified orgs. Query params: `category_id`, `organization_id` |
| `GET` | `/listings/{listing_id}` | `ListingRead` | Single listing. 403 if unverified org and viewer is not a member |
| `GET` | `/listings/categories/` | `list[ListingCategoryRead]` | Verified categories with listing counts |

### Organization-scoped endpoints

| Method | Path | Auth | Response | Description |
|--------|------|------|----------|-------------|
| `POST` | `/organizations/{org_id}/listings/` | Org Editor | `ListingRead` (201) | Create listing |
| `PATCH` | `/organizations/{org_id}/listings/{listing_id}` | Org Editor | `ListingRead` | Update listing |
| `DELETE` | `/organizations/{org_id}/listings/{listing_id}` | Org Editor | 204 | Delete listing |
| `PATCH` | `/organizations/{org_id}/listings/{listing_id}/status` | Org Editor | `ListingRead` | Change status |
| `GET` | `/organizations/{org_id}/listings/` | Org Member | `list[ListingRead]` | List all org listings (any status) |
| `GET` | `/organizations/{org_id}/listings/categories/` | Org Member | `list[ListingCategoryRead]` | Org categories + verified global |
| `POST` | `/organizations/{org_id}/listings/categories/` | Org Editor | `ListingCategoryRead` (201) | Create org-scoped category |

## Testing Strategy

Integration tests with real test DB, following existing patterns (`AsyncClient` + `ASGITransport`, table truncation between tests).

### Fixtures to add in `conftest.py`

- `create_listing(org, user, **overrides)` — factory creating a listing with defaults
- `create_category(org?, user?, name, verified?)` — factory for categories
- `seed_categories` — ensure seed categories exist for public listing tests

### Test classes

| Class | Coverage |
|-------|----------|
| `TestCreateListing` | Happy path, missing required fields, invalid category, permissions (non-editor rejected), org editor from different org rejected |
| `TestUpdateListing` | Partial update, category change, wrong org, permission check |
| `TestDeleteListing` | Happy path, not found, wrong org, permissions |
| `TestChangeListingStatus` | All 4 status values, permissions |
| `TestListOrgListings` | Returns all statuses, correct ordering, membership required |
| `TestPublicListings` | Only published+verified visible, category filter, org filter, unverified org excluded |
| `TestGetListing` | Public access to published+verified, unverified org returns 403 for non-member, member can access |
| `TestCreateCategory` | Happy path, editor permission required |
| `TestListPublicCategories` | Only verified, ordered by listing count |
| `TestListOrgCategories` | Includes org-specific + global verified, count scoped to org |
