# Custom Ordering for List Endpoints

Add client-controlled sorting via `order_by` query parameter to paginated list endpoints.

## Scope

9 paginated endpoints across 5 modules:

| Endpoint | Sortable fields | Default |
|----------|----------------|---------|
| `GET /listings/` | `price`, `name`, `created_at`, `updated_at` | `-updated_at` |
| `GET /organizations/{org_id}/listings/` | `price`, `name`, `created_at`, `updated_at` | `-updated_at` |
| `GET /orders/` | `created_at`, `updated_at`, `estimated_cost`, `requested_start_date` | `-updated_at` |
| `GET /organizations/{org_id}/orders/` | `created_at`, `updated_at`, `estimated_cost`, `requested_start_date` | `-updated_at` |
| `GET /organizations/` | `short_name`, `created_at` | `-created_at` |
| `GET /private/organizations/` | `short_name`, `created_at` | `-created_at` |
| `GET /private/users/` | `email`, `surname`, `created_at` | `-created_at` |
| `GET /organizations/{org_id}/members` | `role`, `created_at` | `-created_at` |
| `GET /users/me/organizations` | `created_at` | `-created_at` |

**Excluded** (fixed ordering):
- Chat messages — chronological only
- Categories — sorted by listing count
- Reservations — not paginated
- User search — not paginated

## API Contract

Single `order_by` query parameter:
- Prefix `-` for descending, no prefix for ascending
- Examples: `?order_by=-price`, `?order_by=name`
- `None` (omitted) → uses endpoint default
- Invalid field → 422 with error listing allowed fields
- `-id` is always appended as a tiebreaker, never exposed to clients

## Core Primitive

A factory function in `app/core/pagination.py`:

```python
def ordering_dependency(
    allowed_fields: dict[str, str],  # {api_name: model_field}
    default: str,                     # e.g. "-updated_at"
) -> type:
```

Returns a FastAPI-compatible dependency class with:
- `order_by: str | None = Query(None)` as its `__init__` parameter
- An `ordering` property returning `tuple[str, ...]` for `paginate()`
- Validation: strips `-` prefix, checks field against `allowed_fields`, raises `RequestValidationError` on mismatch (goes through existing `validation_error_handler` → 422)
- The `-id` tiebreaker is appended automatically

## Per-Endpoint Configuration

Each ordering dependency is defined in the corresponding `dependencies.py` file:

**`app/listings/dependencies.py`:**
```python
ListingOrdering = ordering_dependency(
    allowed_fields={"price": "price", "name": "name", "created_at": "created_at", "updated_at": "updated_at"},
    default="-updated_at",
)
```

**`app/orders/dependencies.py`:**
```python
OrderOrdering = ordering_dependency(
    allowed_fields={"created_at": "created_at", "updated_at": "updated_at", "estimated_cost": "estimated_cost", "requested_start_date": "requested_start_date"},
    default="-updated_at",
)
```

**`app/organizations/dependencies.py`:**
```python
OrganizationOrdering = ordering_dependency(
    allowed_fields={"short_name": "short_name", "created_at": "created_at"},
    default="-created_at",
)

MemberOrdering = ordering_dependency(
    allowed_fields={"role": "role", "created_at": "created_at"},
    default="-created_at",
)
```

**`app/admin/dependencies.py`** (new file):
```python
UserOrdering = ordering_dependency(
    allowed_fields={"email": "email", "surname": "surname", "created_at": "created_at"},
    default="-created_at",
)
```

## Service Layer Changes

Each affected service function stops hardcoding the ordering tuple and accepts it as a parameter:

```python
# Before
async def list_public_listings(storage, params, filters) -> PaginatedResponse[ListingRead]:
    ...
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))

# After
async def list_public_listings(storage, params, filters, ordering: tuple[str, ...]) -> PaginatedResponse[ListingRead]:
    ...
    items, next_cursor, has_more = await paginate(qs, params, ordering=ordering)
```

Affected functions (9 total):
- `listings/service.py`: `list_org_listings`, `list_public_listings`
- `orders/service.py`: `list_user_orders`, `list_org_orders`
- `organizations/service.py`: `list_public_organizations`, `list_members`, `list_user_organizations`
- Admin service calls for users and organizations

The router extracts `ordering.ordering` and passes it to the service. The service has no knowledge of allowed fields or validation.

## Testing Strategy

### Unit tests (`tests/unit/test_ordering.py`)

Test the ordering dependency factory:
- Valid field without prefix → ascending tuple `("price", "-id")`
- Valid field with `-` prefix → descending tuple `("-price", "-id")`
- `None` → default ordering tuple
- Invalid field → `RequestValidationError` (422)
- Invalid format (empty string, `--price`) → `RequestValidationError` (422)
- Each configured dependency has correct allowed fields and default

### Integration tests (per-endpoint, in existing test files)

For each of the 9 endpoints:
- Default ordering — omit `order_by`, verify items in expected default order
- Ascending sort — `?order_by=<field>`, verify ascending order
- Descending sort — `?order_by=-<field>`, verify descending order
- Invalid field — `?order_by=nonexistent`, verify 422 response with allowed fields
- Pagination + custom ordering — cursor pagination with non-default ordering, verify no duplicates/gaps across pages

### Pagination cursor correctness (`tests/db/test_pagination_ordering.py`)

Dedicated test for cursor correctness with custom ordering:
- Create 5+ items with distinct values for the sort field
- Fetch page 1 with `limit=2` and custom ordering
- Fetch page 2 using returned cursor
- Assert no duplicates, no gaps, correct order across both pages
