# Custom Ordering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add client-controlled `order_by` query parameter to 9 paginated list endpoints across listings, orders, organizations, members, and admin users.

**Architecture:** A reusable `ordering_dependency` factory in `app/core/pagination.py` produces FastAPI dependency classes configured with allowed fields and a default. Each endpoint declares its own ordering dependency. Service functions accept the ordering tuple instead of hardcoding it. Invalid `order_by` values produce 422 via `RequestValidationError`.

**Tech Stack:** FastAPI dependencies, Tortoise ORM ordering, cursor-based pagination, pytest + httpx

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `app/core/pagination.py` | Modify | Add `ordering_dependency` factory function |
| `app/listings/dependencies.py` | Modify | Add `ListingOrdering` |
| `app/listings/service.py` | Modify | Accept `ordering` param in `list_org_listings`, `list_public_listings` |
| `app/listings/router.py` | Modify | Wire `ListingOrdering` dependency to both list endpoints |
| `app/orders/dependencies.py` | Modify | Add `OrderOrdering` |
| `app/orders/service.py` | Modify | Accept `ordering` param in `list_user_orders`, `list_org_orders` |
| `app/orders/router.py` | Modify | Wire `OrderOrdering` dependency to both list endpoints |
| `app/organizations/dependencies.py` | Modify | Add `OrganizationOrdering`, `MemberOrdering` |
| `app/organizations/service.py` | Modify | Accept `ordering` param in `list_public_organizations`, `list_all_organizations`, `list_members`, `list_user_organizations` |
| `app/organizations/router.py` | Modify | Wire `OrganizationOrdering` to `list_organizations` |
| `app/organizations/members_router.py` | Modify | Wire `MemberOrdering` to `list_members` |
| `app/admin/dependencies.py` | Create | Add `UserOrdering`, re-export `OrganizationOrdering` |
| `app/admin/router.py` | Modify | Wire `UserOrdering` and `OrganizationOrdering` to admin list endpoints |
| `app/users/router.py` | Modify | Wire `OrganizationOrdering` to `list_my_organizations` |
| `app/users/service.py` | Modify | Accept `ordering` param in `list_users` |
| `tests/unit/test_ordering.py` | Create | Unit tests for `ordering_dependency` |
| `tests/db/test_listings.py` | Modify | Ordering integration tests for listing endpoints |
| `tests/db/test_orders.py` | Modify | Ordering integration tests for order endpoints |
| `tests/db/test_organizations.py` | Modify | Ordering integration tests for org + member endpoints |
| `tests/db/test_admin.py` | Modify | Ordering integration tests for admin endpoints |
| `tests/db/test_users.py` | Modify | Ordering integration tests for user org listing |
| `tests/db/test_pagination.py` | Modify | Cross-page cursor correctness with custom ordering |

---

### Task 1: Core `ordering_dependency` factory + unit tests

**Files:**
- Modify: `app/core/pagination.py:1-10` (imports), append factory after line 112
- Create: `tests/unit/test_ordering.py`

- [ ] **Step 1: Write unit tests for the ordering dependency**

Create `tests/unit/test_ordering.py`:

```python
import pytest
from fastapi.exceptions import RequestValidationError

from app.core.pagination import ordering_dependency


class TestOrderingDependency:
    def setup_method(self) -> None:
        self.cls = ordering_dependency(
            allowed_fields={"price": "price", "name": "name", "created_at": "created_at"},
            default="-created_at",
        )

    def test_default_ordering(self) -> None:
        dep = self.cls(order_by=None)
        assert dep.ordering == ("-created_at", "-id")

    def test_ascending_field(self) -> None:
        dep = self.cls(order_by="price")
        assert dep.ordering == ("price", "id")

    def test_descending_field(self) -> None:
        dep = self.cls(order_by="-price")
        assert dep.ordering == ("-price", "-id")

    def test_field_name_mapping(self) -> None:
        cls = ordering_dependency(
            allowed_fields={"cost": "estimated_cost"},
            default="-estimated_cost",
        )
        dep = cls(order_by="-cost")
        assert dep.ordering == ("-estimated_cost", "-id")

    def test_invalid_field_raises_validation_error(self) -> None:
        with pytest.raises(RequestValidationError):
            self.cls(order_by="nonexistent")

    def test_empty_string_raises_validation_error(self) -> None:
        with pytest.raises(RequestValidationError):
            self.cls(order_by="")

    def test_double_dash_raises_validation_error(self) -> None:
        with pytest.raises(RequestValidationError):
            self.cls(order_by="--price")

    def test_tiebreaker_direction_matches_primary_desc(self) -> None:
        dep = self.cls(order_by="-name")
        assert dep.ordering == ("-name", "-id")

    def test_tiebreaker_direction_matches_primary_asc(self) -> None:
        dep = self.cls(order_by="name")
        assert dep.ordering == ("name", "id")

    def test_default_with_ascending(self) -> None:
        cls = ordering_dependency(
            allowed_fields={"name": "name"},
            default="name",
        )
        dep = cls(order_by=None)
        assert dep.ordering == ("name", "id")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_ordering.py -v`
Expected: FAIL — `ordering_dependency` does not exist yet.

- [ ] **Step 3: Implement `ordering_dependency` factory**

Add import to `app/core/pagination.py` at the top (after existing imports):

```python
from fastapi.exceptions import RequestValidationError
```

Append after the `paginate` function (after line 112):

```python
def ordering_dependency(
    allowed_fields: dict[str, str],
    default: str,
) -> type:
    """Create a FastAPI dependency class for validating and parsing order_by query params.

    Args:
        allowed_fields: Mapping of client-facing field names to ORM field names.
        default: Default ordering field (prefix with '-' for descending).

    Returns:
        A class usable as a FastAPI dependency with an `ordering` property.
    """
    _allowed = allowed_fields
    _default = default

    class _OrderingParams:
        def __init__(self, order_by: str | None = None) -> None:
            raw = order_by if order_by is not None else _default
            descending = raw.startswith("-")
            field_name = raw[1:] if descending else raw

            if field_name not in _allowed:
                allowed_list = ", ".join(sorted(_allowed))
                raise RequestValidationError(
                    [
                        {
                            "loc": ("query", "order_by"),
                            "msg": f"Invalid order_by field '{field_name}'. Allowed: {allowed_list}",
                            "type": "value_error",
                        },
                    ],
                )

            model_field = _allowed[field_name]
            prefix = "-" if descending else ""
            tiebreaker = "-id" if descending else "id"
            self.ordering: tuple[str, ...] = (f"{prefix}{model_field}", tiebreaker)

    return _OrderingParams
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_ordering.py -v`
Expected: All 11 tests PASS.

- [ ] **Step 5: Run type checker**

Run: `task mypy`
Expected: PASS with no new errors.

- [ ] **Step 6: Commit**

```bash
git add app/core/pagination.py tests/unit/test_ordering.py
git commit -m "feat(pagination): add ordering_dependency factory for custom sort params"
```

---

### Task 2: Listings ordering

**Files:**
- Modify: `app/listings/dependencies.py:1-4` (imports), append after `ListingFilter`
- Modify: `app/listings/service.py:201-216` (`list_org_listings`), `app/listings/service.py:219-238` (`list_public_listings`)
- Modify: `app/listings/router.py:1-8` (imports), `app/listings/router.py:73-84` (`list_org_listings`), `app/listings/router.py:96-105` (`list_public_listings`)
- Modify: `tests/db/test_listings.py`

- [ ] **Step 1: Write integration tests for listing ordering**

Add to `tests/db/test_listings.py` at the end:

```python
class TestListingOrdering:
    async def test_public_listings_default_order(
        self,
        client: AsyncClient,
        verified_org: tuple[Any, str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        cat_id = seed_categories[0].id

        for i, name in enumerate(["Alpha", "Beta", "Gamma"]):
            resp = await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": name, "category_id": cat_id, "price": (i + 1) * 1000.0},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201
            listing_id = resp.json()["id"]
            await client.patch(
                f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
                json={"status": "published"},
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = await client.get("/api/v1/listings/")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 3
        # Default: -updated_at (last updated first)
        assert items[0]["name"] == "Gamma"

    async def test_public_listings_order_by_price_asc(
        self,
        client: AsyncClient,
        verified_org: tuple[Any, str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        cat_id = seed_categories[0].id

        for i, (name, price) in enumerate([("Cheap", 100.0), ("Mid", 500.0), ("Expensive", 900.0)]):
            resp = await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": name, "category_id": cat_id, "price": price},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201
            listing_id = resp.json()["id"]
            await client.patch(
                f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
                json={"status": "published"},
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = await client.get("/api/v1/listings/", params={"order_by": "price"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        prices = [item["price"] for item in items]
        assert prices == sorted(prices)

    async def test_public_listings_order_by_price_desc(
        self,
        client: AsyncClient,
        verified_org: tuple[Any, str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        cat_id = seed_categories[0].id

        for name, price in [("Cheap", 100.0), ("Mid", 500.0), ("Expensive", 900.0)]:
            resp = await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": name, "category_id": cat_id, "price": price},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201
            listing_id = resp.json()["id"]
            await client.patch(
                f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
                json={"status": "published"},
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = await client.get("/api/v1/listings/", params={"order_by": "-price"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        prices = [item["price"] for item in items]
        assert prices == sorted(prices, reverse=True)

    async def test_public_listings_order_by_name(
        self,
        client: AsyncClient,
        verified_org: tuple[Any, str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        cat_id = seed_categories[0].id

        for name in ["Gamma", "Alpha", "Beta"]:
            resp = await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": name, "category_id": cat_id, "price": 1000.0},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201
            listing_id = resp.json()["id"]
            await client.patch(
                f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
                json={"status": "published"},
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = await client.get("/api/v1/listings/", params={"order_by": "name"})
        assert resp.status_code == 200
        names = [item["name"] for item in resp.json()["items"]]
        assert names == sorted(names)

    async def test_public_listings_invalid_order_by(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/listings/", params={"order_by": "nonexistent"})
        assert resp.status_code == 422

    async def test_org_listings_order_by_price(
        self,
        client: AsyncClient,
        verified_org: tuple[Any, str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        cat_id = seed_categories[0].id

        for name, price in [("Cheap", 100.0), ("Expensive", 900.0)]:
            await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": name, "category_id": cat_id, "price": price},
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/listings/",
            params={"order_by": "price"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        prices = [item["price"] for item in resp.json()["items"]]
        assert prices == sorted(prices)

    async def test_public_listings_pagination_with_custom_order(
        self,
        client: AsyncClient,
        verified_org: tuple[Any, str],
        seed_categories: list[ListingCategory],
    ) -> None:
        org_data, token = verified_org
        org_id = org_data["id"]
        cat_id = seed_categories[0].id

        for i in range(5):
            resp = await client.post(
                f"/api/v1/organizations/{org_id}/listings/",
                json={"name": f"Item {i}", "category_id": cat_id, "price": (i + 1) * 100.0},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201
            listing_id = resp.json()["id"]
            await client.patch(
                f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
                json={"status": "published"},
                headers={"Authorization": f"Bearer {token}"},
            )

        # Page 1
        resp1 = await client.get("/api/v1/listings/", params={"order_by": "price", "limit": 2})
        assert resp1.status_code == 200
        body1 = resp1.json()
        assert len(body1["items"]) == 2
        assert body1["has_more"] is True

        # Page 2
        resp2 = await client.get(
            "/api/v1/listings/",
            params={"order_by": "price", "limit": 2, "cursor": body1["next_cursor"]},
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert len(body2["items"]) == 2

        # Page 3
        resp3 = await client.get(
            "/api/v1/listings/",
            params={"order_by": "price", "limit": 2, "cursor": body2["next_cursor"]},
        )
        body3 = resp3.json()
        assert len(body3["items"]) == 1
        assert body3["has_more"] is False

        # All prices ascending, no duplicates
        all_prices = [item["price"] for item in body1["items"] + body2["items"] + body3["items"]]
        assert all_prices == sorted(all_prices)
        all_ids = [item["id"] for item in body1["items"] + body2["items"] + body3["items"]]
        assert len(all_ids) == len(set(all_ids))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_listings.py::TestListingOrdering -v`
Expected: FAIL — `order_by` query param not wired up yet.

- [ ] **Step 3: Add `ListingOrdering` dependency**

In `app/listings/dependencies.py`, add import at top:

```python
from app.core.pagination import ordering_dependency
```

Append after the `ListingFilter` class (after line 98):

```python
ListingOrdering = ordering_dependency(
    allowed_fields={"price": "price", "name": "name", "created_at": "created_at", "updated_at": "updated_at"},
    default="-updated_at",
)
```

- [ ] **Step 4: Update listing service functions to accept ordering**

In `app/listings/service.py`, change `list_org_listings` (lines 201-216):

Replace:
```python
async def list_org_listings(
    org_id: str,
    storage: StorageClient,
    params: CursorParams,
    filters: ListingFilter,
) -> PaginatedResponse[ListingRead]:
    qs = Listing.filter(organization_id=org_id)
    qs = _apply_listing_filters(qs, filters)
    items, next_cursor, has_more = await paginate(
        qs.prefetch_related("category"),
        params,
        ordering=("-updated_at", "-id"),
    )
```

With:
```python
async def list_org_listings(
    org_id: str,
    storage: StorageClient,
    params: CursorParams,
    filters: ListingFilter,
    ordering: tuple[str, ...],
) -> PaginatedResponse[ListingRead]:
    qs = Listing.filter(organization_id=org_id)
    qs = _apply_listing_filters(qs, filters)
    items, next_cursor, has_more = await paginate(
        qs.prefetch_related("category"),
        params,
        ordering=ordering,
    )
```

Change `list_public_listings` (lines 219-238):

Replace:
```python
async def list_public_listings(
    storage: StorageClient,
    params: CursorParams,
    filters: ListingFilter,
) -> PaginatedResponse[ListingRead]:
```

With:
```python
async def list_public_listings(
    storage: StorageClient,
    params: CursorParams,
    filters: ListingFilter,
    ordering: tuple[str, ...],
) -> PaginatedResponse[ListingRead]:
```

And replace:
```python
    items, next_cursor, has_more = await paginate(
        qs.prefetch_related("category"),
        params,
        ordering=("-updated_at", "-id"),
    )
```

With:
```python
    items, next_cursor, has_more = await paginate(
        qs.prefetch_related("category"),
        params,
        ordering=ordering,
    )
```

- [ ] **Step 5: Wire ordering in listing router**

In `app/listings/router.py`, update the import (line 8):

Replace:
```python
from app.listings.dependencies import ListingFilter, resolve_listing, resolve_org_listing, resolve_public_listing
```

With:
```python
from app.listings.dependencies import ListingFilter, ListingOrdering, resolve_listing, resolve_org_listing, resolve_public_listing
```

Update `list_org_listings` (lines 73-84):

Replace:
```python
async def list_org_listings(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
    filters: Annotated[ListingFilter, Depends()],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[ListingRead]:
    """List all listings for the organization regardless of status. Org members only."""
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_org_listings(org_id, storage, params, filters)
```

With:
```python
async def list_org_listings(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
    filters: Annotated[ListingFilter, Depends()],
    ordering: Annotated[ListingOrdering, Depends()],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[ListingRead]:
    """List all listings for the organization regardless of status. Org members only."""
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_org_listings(org_id, storage, params, filters, ordering.ordering)
```

Update `list_public_listings` (lines 96-105):

Replace:
```python
async def list_public_listings(
    filters: Annotated[ListingFilter, Depends()],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[ListingRead]:
    """Browse published listings from verified organizations only."""
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_public_listings(storage, params, filters)
```

With:
```python
async def list_public_listings(
    filters: Annotated[ListingFilter, Depends()],
    ordering: Annotated[ListingOrdering, Depends()],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[ListingRead]:
    """Browse published listings from verified organizations only."""
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_public_listings(storage, params, filters, ordering.ordering)
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/db/test_listings.py -v`
Expected: All tests PASS (both new ordering tests and existing tests).

- [ ] **Step 7: Run type checker and linter**

Run: `task ruff:fix && task mypy`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/listings/dependencies.py app/listings/service.py app/listings/router.py tests/db/test_listings.py
git commit -m "feat(listings): add order_by query parameter to listing list endpoints"
```

---

### Task 3: Orders ordering

**Files:**
- Modify: `app/orders/dependencies.py:1-4` (imports), append after `OrderFilter`
- Modify: `app/orders/service.py:190-213` (`list_user_orders`, `list_org_orders`)
- Modify: `app/orders/router.py:1-13` (imports), `app/orders/router.py:29-37`, `app/orders/router.py:64-73`
- Modify: `tests/db/test_orders.py`

- [ ] **Step 1: Write integration tests for order ordering**

Add to `tests/db/test_orders.py` at the end. Note: the file uses a module-level `_create_order` helper and `_today` helper — reuse them.

```python
class TestOrderOrdering:
    async def test_user_orders_default_order(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing_id, renter_token, start_offset=10)

        resp = await client.get(
            "/api/v1/orders/",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        # Default: -updated_at
        dates = [item["updated_at"] for item in items]
        assert dates == sorted(dates, reverse=True)

    async def test_user_orders_order_by_created_at_asc(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing_id, renter_token, start_offset=10)

        resp = await client.get(
            "/api/v1/orders/",
            params={"order_by": "created_at"},
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        dates = [item["created_at"] for item in items]
        assert dates == sorted(dates)

    async def test_user_orders_order_by_requested_start_date(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        await _create_order(client, listing_id, renter_token, start_offset=20)
        await _create_order(client, listing_id, renter_token, start_offset=5)

        resp = await client.get(
            "/api/v1/orders/",
            params={"order_by": "requested_start_date"},
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        dates = [item["requested_start_date"] for item in items]
        assert dates == sorted(dates)

    async def test_user_orders_invalid_order_by(
        self,
        client: AsyncClient,
        renter_token: str,
    ) -> None:
        resp = await client.get(
            "/api/v1/orders/",
            params={"order_by": "invalid"},
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 422

    async def test_org_orders_order_by_created_at(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing_id, renter_token, start_offset=10)

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/",
            params={"order_by": "created_at"},
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        dates = [item["created_at"] for item in items]
        assert dates == sorted(dates)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_orders.py::TestOrderOrdering -v`
Expected: FAIL — `order_by` query param not recognized.

- [ ] **Step 3: Add `OrderOrdering` dependency**

In `app/orders/dependencies.py`, add import at top:

```python
from app.core.pagination import ordering_dependency
```

Append after the `OrderFilter` class (after line 50):

```python
OrderOrdering = ordering_dependency(
    allowed_fields={
        "created_at": "created_at",
        "updated_at": "updated_at",
        "estimated_cost": "estimated_cost",
        "requested_start_date": "requested_start_date",
    },
    default="-updated_at",
)
```

- [ ] **Step 4: Update order service functions**

In `app/orders/service.py`, change `list_user_orders` (lines 190-200):

Replace:
```python
async def list_user_orders(
    user: User,
    params: CursorParams,
    filters: OrderFilter,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(requester=user)
    qs = _apply_order_filters(qs, filters)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
```

With:
```python
async def list_user_orders(
    user: User,
    params: CursorParams,
    filters: OrderFilter,
    ordering: tuple[str, ...],
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(requester=user)
    qs = _apply_order_filters(qs, filters)
    items, next_cursor, has_more = await paginate(qs, params, ordering=ordering)
```

Change `list_org_orders` (lines 203-213):

Replace:
```python
async def list_org_orders(
    org_id: str,
    params: CursorParams,
    filters: OrderFilter,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(organization_id=org_id)
    qs = _apply_order_filters(qs, filters)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
```

With:
```python
async def list_org_orders(
    org_id: str,
    params: CursorParams,
    filters: OrderFilter,
    ordering: tuple[str, ...],
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(organization_id=org_id)
    qs = _apply_order_filters(qs, filters)
    items, next_cursor, has_more = await paginate(qs, params, ordering=ordering)
```

- [ ] **Step 5: Wire ordering in order router**

In `app/orders/router.py`, update the import (line 8):

Replace:
```python
from app.orders.dependencies import OrderFilter, get_org_order_or_404, require_order_requester
```

With:
```python
from app.orders.dependencies import OrderFilter, OrderOrdering, get_org_order_or_404, require_order_requester
```

Update `list_my_orders` (lines 29-37):

Replace:
```python
async def list_my_orders(
    user: Annotated[User, Depends(require_active_user)],
    filters: Annotated[OrderFilter, Depends()],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[OrderRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_user_orders(user, params, filters)
```

With:
```python
async def list_my_orders(
    user: Annotated[User, Depends(require_active_user)],
    filters: Annotated[OrderFilter, Depends()],
    ordering: Annotated[OrderOrdering, Depends()],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[OrderRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_user_orders(user, params, filters, ordering.ordering)
```

Update `list_org_orders` (lines 64-73):

Replace:
```python
async def list_org_orders(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_editor)],
    filters: Annotated[OrderFilter, Depends()],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[OrderRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_org_orders(org_id, params, filters)
```

With:
```python
async def list_org_orders(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_editor)],
    filters: Annotated[OrderFilter, Depends()],
    ordering: Annotated[OrderOrdering, Depends()],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[OrderRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_org_orders(org_id, params, filters, ordering.ordering)
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/db/test_orders.py -v`
Expected: All tests PASS.

- [ ] **Step 7: Run type checker and linter**

Run: `task ruff:fix && task mypy`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/orders/dependencies.py app/orders/service.py app/orders/router.py tests/db/test_orders.py
git commit -m "feat(orders): add order_by query parameter to order list endpoints"
```

---

### Task 4: Organizations ordering (public, admin, members, user orgs)

**Files:**
- Modify: `app/organizations/dependencies.py:1-4` (imports), append at end
- Modify: `app/organizations/service.py:138-175` (4 service functions)
- Modify: `app/organizations/router.py:42-71` (`list_organizations`)
- Modify: `app/organizations/members_router.py:77-85` (`list_members`)
- Create: `app/admin/dependencies.py`
- Modify: `app/admin/router.py:1-15` (imports), `app/admin/router.py:64-96` (`list_all_organizations`)
- Modify: `app/users/router.py:69-87` (`list_my_organizations`)
- Modify: `tests/db/test_organizations.py`, `tests/db/test_admin.py`, `tests/db/test_users.py`

- [ ] **Step 1: Write integration tests for organization ordering**

Add to `tests/db/test_organizations.py` at the end:

```python
class TestOrganizationOrdering:
    async def test_public_orgs_default_order(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        _, token1 = await create_organization(
            token=None,
            inn="7707083893",
        )
        _, token2 = await create_organization(
            token=None,
            inn="7707083893",
        )

        # Verify both orgs
        from app.core.enums import OrganizationStatus
        from app.organizations.models import Organization

        await Organization.all().update(status=OrganizationStatus.VERIFIED)

        resp = await client.get("/api/v1/organizations/")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 2
        # Default: -created_at
        dates = [item["id"] for item in items]
        assert dates == list(dict.fromkeys(dates))  # no duplicates

    async def test_public_orgs_order_by_short_name(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        await create_organization(token=None, inn="7707083893")
        await create_organization(token=None, inn="7707083893")

        from app.core.enums import OrganizationStatus
        from app.organizations.models import Organization

        await Organization.all().update(status=OrganizationStatus.VERIFIED)

        resp = await client.get("/api/v1/organizations/", params={"order_by": "short_name"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        names = [item["short_name"] for item in items]
        assert names == sorted(names)

    async def test_public_orgs_invalid_order_by(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/organizations/", params={"order_by": "invalid"})
        assert resp.status_code == 422


class TestMemberOrdering:
    async def test_members_order_by_created_at_asc(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        org_id = org_data["id"]

        # Invite a second member
        _, token2 = await create_user(email="member2@example.com", phone="+79990000002")
        user2_resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token2}"})
        user2_email = user2_resp.json()["email"]

        await client.post(
            f"/api/v1/organizations/{org_id}/members/invite",
            json={"email": user2_email, "role": "viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Accept invite
        invites = await client.get(
            f"/api/v1/organizations/{org_id}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        pending = [m for m in invites.json()["items"] if m["status"] == "pending"]
        if pending:
            await client.patch(
                f"/api/v1/organizations/{org_id}/members/{pending[0]['id']}/approve",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/members",
            params={"order_by": "created_at"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        dates = [item["created_at"] for item in items]
        assert dates == sorted(dates)

    async def test_members_invalid_order_by(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        org_id = org_data["id"]
        resp = await client.get(
            f"/api/v1/organizations/{org_id}/members",
            params={"order_by": "invalid"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
```

Add to `tests/db/test_admin.py` at the end:

```python
class TestAdminOrganizationOrdering:
    async def test_admin_orgs_order_by_short_name(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_organization: Any,
    ) -> None:
        _, admin_token = admin_user
        await create_organization(token=None, inn="7707083893")
        await create_organization(token=None, inn="7707083893")

        resp = await client.get(
            "/api/v1/private/organizations/",
            params={"order_by": "short_name"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        names = [item["short_name"] for item in items]
        assert names == sorted(names)

    async def test_admin_orgs_invalid_order_by(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        _, admin_token = admin_user
        resp = await client.get(
            "/api/v1/private/organizations/",
            params={"order_by": "invalid"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422
```

Add to `tests/db/test_users.py` at the end:

```python
class TestUserOrganizationOrdering:
    async def test_my_orgs_order_by_created_at_asc(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org1, token = await create_organization()
        # Create a second org with same user
        org2, _ = await create_organization(token=token, inn="7707083893")

        resp = await client.get(
            "/api/v1/users/me/organizations",
            params={"order_by": "created_at"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    async def test_my_orgs_invalid_order_by(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        _, token = await create_organization()
        resp = await client.get(
            "/api/v1/users/me/organizations",
            params={"order_by": "invalid"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    async def test_my_orgs_short_name_not_allowed(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        _, token = await create_organization()
        resp = await client.get(
            "/api/v1/users/me/organizations",
            params={"order_by": "short_name"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_organizations.py::TestOrganizationOrdering tests/db/test_organizations.py::TestMemberOrdering tests/db/test_admin.py::TestAdminOrganizationOrdering tests/db/test_users.py::TestUserOrganizationOrdering -v`
Expected: FAIL.

- [ ] **Step 3: Add ordering dependencies**

In `app/organizations/dependencies.py`, add import:

```python
from app.core.pagination import ordering_dependency
```

Append at the end (after line 67):

```python
OrganizationOrdering = ordering_dependency(
    allowed_fields={"short_name": "short_name", "created_at": "created_at"},
    default="-created_at",
)

MemberOrdering = ordering_dependency(
    allowed_fields={"role": "role", "created_at": "created_at"},
    default="-created_at",
)

UserOrgOrdering = ordering_dependency(
    allowed_fields={"created_at": "created_at"},
    default="-created_at",
)
```

Create `app/admin/dependencies.py`:

```python
from app.core.pagination import ordering_dependency

UserOrdering = ordering_dependency(
    allowed_fields={"email": "email", "surname": "surname", "created_at": "created_at"},
    default="-created_at",
)
```

- [ ] **Step 4: Update organization service functions**

In `app/organizations/service.py`, change `list_user_organizations` (lines 138-150):

Replace:
```python
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

With:
```python
async def list_user_organizations(
    user: User,
    params: CursorParams,
    ordering: tuple[str, ...],
) -> tuple[list[Organization], str | None, bool]:
    qs = Membership.filter(
        user=user,
        status=MembershipStatus.MEMBER,
    ).prefetch_related("organization__contacts")

    items, next_cursor, has_more = await paginate(qs, params, ordering=ordering)
    orgs = [m.organization for m in items]
    return orgs, next_cursor, has_more
```

Change `list_public_organizations` (lines 153-161):

Replace:
```python
async def list_public_organizations(
    params: CursorParams,
    search: str | None = None,
) -> tuple[list[Organization], str | None, bool]:
    qs = Organization.filter(status=OrganizationStatus.VERIFIED)
    if search:
        qs = qs.filter(Q(short_name__icontains=search) | Q(full_name__icontains=search))
    return await paginate(qs, params, ordering=("-created_at", "-id"))
```

With:
```python
async def list_public_organizations(
    params: CursorParams,
    ordering: tuple[str, ...],
    search: str | None = None,
) -> tuple[list[Organization], str | None, bool]:
    qs = Organization.filter(status=OrganizationStatus.VERIFIED)
    if search:
        qs = qs.filter(Q(short_name__icontains=search) | Q(full_name__icontains=search))
    return await paginate(qs, params, ordering=ordering)
```

Change `list_all_organizations` (lines 164-175):

Replace:
```python
async def list_all_organizations(
    params: CursorParams,
    search: str | None = None,
    status: OrganizationStatus | None = None,
) -> tuple[list[Organization], str | None, bool]:
    qs = Organization.all()
    if search:
        qs = qs.filter(Q(short_name__icontains=search) | Q(full_name__icontains=search))
    if status:
        qs = qs.filter(status=status)
    return await paginate(qs, params, ordering=("-created_at", "-id"))
```

With:
```python
async def list_all_organizations(
    params: CursorParams,
    ordering: tuple[str, ...],
    search: str | None = None,
    status: OrganizationStatus | None = None,
) -> tuple[list[Organization], str | None, bool]:
    qs = Organization.all()
    if search:
        qs = qs.filter(Q(short_name__icontains=search) | Q(full_name__icontains=search))
    if status:
        qs = qs.filter(status=status)
    return await paginate(qs, params, ordering=ordering)
```

Change `list_members` (lines 343-351):

Replace:
```python
async def list_members(
    org_id: str,
    params: CursorParams,
) -> PaginatedResponse[MembershipRead]:
    qs = Membership.filter(organization_id=org_id)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-created_at", "-id"))
```

With:
```python
async def list_members(
    org_id: str,
    params: CursorParams,
    ordering: tuple[str, ...],
) -> PaginatedResponse[MembershipRead]:
    qs = Membership.filter(organization_id=org_id)
    items, next_cursor, has_more = await paginate(qs, params, ordering=ordering)
```

- [ ] **Step 5: Wire ordering in organization routers**

In `app/organizations/router.py`, update imports (add to line 13):

Replace:
```python
from app.organizations.dependencies import get_dadata_client, require_org_admin, require_org_member
```

With:
```python
from app.organizations.dependencies import OrganizationOrdering, get_dadata_client, require_org_admin, require_org_member
```

Update `list_organizations` (lines 42-71):

Replace:
```python
async def list_organizations(
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
) -> PaginatedResponse[OrganizationListRead]:
    """Browse verified organizations with published listing count."""
    params = CursorParams(cursor=cursor, limit=limit)
    items, next_cursor, has_more = await service.list_public_organizations(params, search=search)
```

With:
```python
async def list_organizations(
    storage: Annotated[StorageClient, Depends(get_storage)],
    ordering: Annotated[OrganizationOrdering, Depends()],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
) -> PaginatedResponse[OrganizationListRead]:
    """Browse verified organizations with published listing count."""
    params = CursorParams(cursor=cursor, limit=limit)
    items, next_cursor, has_more = await service.list_public_organizations(params, ordering.ordering, search=search)
```

In `app/organizations/members_router.py`, update imports (add to line 8):

Replace:
```python
from app.organizations.dependencies import get_org_or_404, require_org_admin, require_org_member
```

With:
```python
from app.organizations.dependencies import MemberOrdering, get_org_or_404, require_org_admin, require_org_member
```

Update `list_members` (lines 77-85):

Replace:
```python
async def list_members(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[MembershipRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_members(org_id, params)
```

With:
```python
async def list_members(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
    ordering: Annotated[MemberOrdering, Depends()],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[MembershipRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_members(org_id, params, ordering.ordering)
```

In `app/admin/router.py`, update imports:

Replace:
```python
from app.core.dependencies import require_platform_admin, require_platform_owner
```

With:
```python
from app.admin.dependencies import UserOrdering
from app.core.dependencies import require_platform_admin, require_platform_owner
from app.organizations.dependencies import OrganizationOrdering
```

Note: `OrganizationOrdering` import needs to be added here too. Also remove the duplicate `from app.core.dependencies` if the linter objects — just merge them into one line.

Update `list_all_organizations` in admin router (lines 64-96):

Replace:
```python
async def list_all_organizations(
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
    status: OrganizationStatus | None = None,
) -> PaginatedResponse[OrganizationListRead]:
    """List all organizations regardless of verification status. Platform Admin only."""
    params = CursorParams(cursor=cursor, limit=limit)
    items, next_cursor, has_more = await org_service.list_all_organizations(params, search=search, status=status)
```

With:
```python
async def list_all_organizations(
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    ordering: Annotated[OrganizationOrdering, Depends()],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
    status: OrganizationStatus | None = None,
) -> PaginatedResponse[OrganizationListRead]:
    """List all organizations regardless of verification status. Platform Admin only."""
    params = CursorParams(cursor=cursor, limit=limit)
    items, next_cursor, has_more = await org_service.list_all_organizations(params, ordering.ordering, search=search, status=status)
```

In `app/users/router.py`, update imports:

Replace:
```python
from app.organizations import service as org_service
```

With:
```python
from app.organizations import service as org_service
from app.organizations.dependencies import UserOrgOrdering
```

Update `list_my_organizations` (lines 69-87):

**Note:** The spec lists `short_name, created_at` for this endpoint, but `list_user_organizations` queries Membership (not Organization). The `paginate()` cursor uses `getattr(last, field)` which doesn't support cross-relation fields like `organization__short_name`. Since users typically have very few orgs, only `created_at` is supported here.

Replace:
```python
async def list_my_organizations(
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[OrganizationRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    orgs, next_cursor, has_more = await org_service.list_user_organizations(user, params)
```

With:
```python
async def list_my_organizations(
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    ordering: Annotated[UserOrgOrdering, Depends()],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[OrganizationRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    orgs, next_cursor, has_more = await org_service.list_user_organizations(user, params, ordering.ordering)
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/db/test_organizations.py tests/db/test_admin.py tests/db/test_users.py -v`
Expected: All tests PASS.

- [ ] **Step 7: Run type checker and linter**

Run: `task ruff:fix && task mypy`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/organizations/dependencies.py app/organizations/service.py app/organizations/router.py app/organizations/members_router.py app/admin/dependencies.py app/admin/router.py app/users/router.py tests/db/test_organizations.py tests/db/test_admin.py tests/db/test_users.py
git commit -m "feat(organizations): add order_by query parameter to org, member, and admin list endpoints"
```

---

### Task 5: Admin users ordering

**Files:**
- Modify: `app/users/service.py:115-139` (`list_users`)
- Modify: `app/admin/router.py:20-31` (`list_users`)
- Modify: `tests/db/test_admin.py`

- [ ] **Step 1: Write integration tests for admin user ordering**

Add to `tests/db/test_admin.py`:

```python
class TestAdminUserOrdering:
    async def test_admin_users_order_by_email(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_user: Any,
    ) -> None:
        _, admin_token = admin_user
        await create_user(email="alice@example.com", phone="+79990000001")
        await create_user(email="bob@example.com", phone="+79990000002")
        await create_user(email="charlie@example.com", phone="+79990000003")

        resp = await client.get(
            "/api/v1/private/users/",
            params={"order_by": "email"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        emails = [item["email"] for item in items]
        assert emails == sorted(emails)

    async def test_admin_users_order_by_surname_desc(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
        create_user: Any,
    ) -> None:
        _, admin_token = admin_user
        await create_user(email="a@example.com", phone="+79990000001", surname="Яковлев")
        await create_user(email="b@example.com", phone="+79990000002", surname="Абрамов")

        resp = await client.get(
            "/api/v1/private/users/",
            params={"order_by": "-surname"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        surnames = [item["surname"] for item in items]
        assert surnames == sorted(surnames, reverse=True)

    async def test_admin_users_invalid_order_by(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        _, admin_token = admin_user
        resp = await client.get(
            "/api/v1/private/users/",
            params={"order_by": "invalid"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_admin.py::TestAdminUserOrdering -v`
Expected: FAIL.

- [ ] **Step 3: Update users service**

In `app/users/service.py`, change `list_users` (lines 115-139):

Replace:
```python
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
```

With:
```python
async def list_users(
    params: CursorParams,
    storage: StorageClient,
    ordering: tuple[str, ...],
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

    items, next_cursor, has_more = await paginate(qs, params, ordering=ordering)
```

- [ ] **Step 4: Wire ordering in admin router for users**

In `app/admin/router.py`, update `list_users` (lines 20-31):

Replace:
```python
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

With:
```python
async def list_users(
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    ordering: Annotated[UserOrdering, Depends()],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
    role: UserRole | None = None,
) -> PaginatedResponse[UserRead]:
    """List all platform users. Supports search by name/email and role filter. Platform Admin only."""
    params = CursorParams(cursor=cursor, limit=limit)
    return await user_service.list_users(params, storage, ordering.ordering, search=search, role=role)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/db/test_admin.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Run type checker and linter**

Run: `task ruff:fix && task mypy`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/users/service.py app/admin/router.py tests/db/test_admin.py
git commit -m "feat(admin): add order_by query parameter to admin user list endpoint"
```

---

### Task 6: Cross-page cursor correctness test

**Files:**
- Modify: `tests/db/test_pagination.py`

- [ ] **Step 1: Write cursor correctness test with custom ordering**

Add to `tests/db/test_pagination.py` at the end:

```python
async def test_paginate_custom_ordering_cursor_correctness(create_user: Any) -> None:
    """Verify cursor pagination produces correct results with non-default ordering."""
    emails = [f"user{i:02d}@example.com" for i in range(7)]
    for i, email in enumerate(emails):
        await create_user(email=email, phone=f"+7999400000{i}")

    # Sort by email ascending — cursor must encode email + id
    all_items: list[Any] = []
    cursor: str | None = None

    for _ in range(10):  # safety limit
        items, cursor, has_more = await paginate(
            User.all(),
            CursorParams(cursor=cursor, limit=3),
            ordering=("email", "id"),
        )
        all_items.extend(items)
        if not has_more:
            break

    assert len(all_items) == 7
    all_emails = [u.email for u in all_items]
    assert all_emails == sorted(all_emails), f"Expected sorted emails, got {all_emails}"
    all_ids = [u.id for u in all_items]
    assert len(all_ids) == len(set(all_ids)), "Duplicate items across pages"


async def test_paginate_descending_custom_field_cursor(create_user: Any) -> None:
    """Verify cursor pagination works with descending custom field ordering."""
    for i in range(5):
        await create_user(
            email=f"desc{i}@example.com",
            phone=f"+7999500000{i}",
            surname=f"Surname{i:02d}",
        )

    items1, cursor1, has_more1 = await paginate(
        User.all(),
        CursorParams(limit=2),
        ordering=("-surname", "-id"),
    )
    assert len(items1) == 2
    assert has_more1 is True
    assert cursor1 is not None

    items2, cursor2, has_more2 = await paginate(
        User.all(),
        CursorParams(cursor=cursor1, limit=2),
        ordering=("-surname", "-id"),
    )
    assert len(items2) == 2

    items3, _cursor3, has_more3 = await paginate(
        User.all(),
        CursorParams(cursor=cursor2, limit=2),
        ordering=("-surname", "-id"),
    )
    assert len(items3) == 1
    assert has_more3 is False

    all_surnames = [u.surname for u in items1 + items2 + items3]
    assert all_surnames == sorted(all_surnames, reverse=True)
    all_ids = [u.id for u in items1 + items2 + items3]
    assert len(all_ids) == len(set(all_ids))
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/db/test_pagination.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Run full test suite**

Run: `task test`
Expected: All tests PASS.

- [ ] **Step 4: Run full CI check**

Run: `task ci`
Expected: ruff + mypy + tests all PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/db/test_pagination.py
git commit -m "test(pagination): add cursor correctness tests for custom ordering"
```
