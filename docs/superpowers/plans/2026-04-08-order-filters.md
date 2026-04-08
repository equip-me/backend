# Order Filtering & Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-value status, listing_id, date range overlap, and search filters to both order list endpoints.

**Architecture:** Create an `OrderFilter` dependency class (same pattern as `ListingFilter` in PR #52), a reusable `_apply_order_filters()` helper in the service layer, and wire both into the existing list endpoints.

**Tech Stack:** FastAPI Query params, Tortoise ORM Q expressions, pytest + httpx AsyncClient

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `app/orders/dependencies.py` | Modify | Add `OrderFilter` class |
| `app/orders/service.py` | Modify | Add `_apply_order_filters()`, update `list_user_orders` and `list_org_orders` signatures |
| `app/orders/router.py` | Modify | Replace `status` param with `OrderFilter` dependency |
| `tests/db/test_orders.py` | Modify | Add `TestListOrdersFilters` test class |

---

### Task 1: Add `OrderFilter` dependency class

**Files:**
- Modify: `app/orders/dependencies.py`

- [ ] **Step 1: Add OrderFilter class**

Add to the end of `app/orders/dependencies.py`:

```python
from datetime import date

from fastapi import Query

from app.core.enums import OrderStatus


class OrderFilter:
    def __init__(
        self,
        *,
        status: Annotated[list[OrderStatus] | None, Query()] = None,
        listing_id: str | None = Query(None),
        date_from: date | None = Query(None),
        date_to: date | None = Query(None),
        search: str | None = Query(None),
    ) -> None:
        self.statuses = status
        self.listing_id = listing_id
        self.date_from = date_from
        self.date_to = date_to
        self.search = search
```

Note: `Annotated` and `Query` are already imported — just add `date`, `OrderStatus` to existing imports. `Query` is not yet imported; add it alongside `Path`.

- [ ] **Step 2: Verify types pass**

Run: `task mypy`
Expected: PASS (no new errors)

- [ ] **Step 3: Commit**

```bash
git add app/orders/dependencies.py
git commit -m "feat(orders): add OrderFilter dependency class"
```

---

### Task 2: Add `_apply_order_filters()` and update service functions

**Files:**
- Modify: `app/orders/service.py`

- [ ] **Step 1: Add `_apply_order_filters` helper**

Add after the existing imports in `app/orders/service.py`:

```python
from tortoise.expressions import Q
from tortoise.queryset import QuerySet

from app.orders.dependencies import OrderFilter
```

Then add the helper function before `list_user_orders`:

```python
def _apply_order_filters(qs: QuerySet[Order], filters: OrderFilter) -> QuerySet[Order]:
    if filters.statuses:
        qs = qs.filter(status__in=filters.statuses)
    if filters.listing_id is not None:
        qs = qs.filter(listing_id=filters.listing_id)
    if filters.date_from is not None:
        qs = qs.filter(requested_end_date__gte=filters.date_from)
    if filters.date_to is not None:
        qs = qs.filter(requested_start_date__lte=filters.date_to)
    if filters.search:
        qs = qs.filter(Q(id__icontains=filters.search) | Q(listing__name__icontains=filters.search))
    return qs
```

- [ ] **Step 2: Update `list_user_orders` signature and body**

Replace the current `list_user_orders` (lines 170–180):

```python
@traced
async def list_user_orders(
    user: User,
    params: CursorParams,
    filters: OrderFilter,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(requester=user)
    qs = _apply_order_filters(qs, filters)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
    order_reads = [OrderRead.model_validate(order) for order in items]
    return PaginatedResponse(items=order_reads, next_cursor=next_cursor, has_more=has_more)
```

- [ ] **Step 3: Update `list_org_orders` signature and body**

Replace the current `list_org_orders` (lines 184–194):

```python
@traced
async def list_org_orders(
    org_id: str,
    params: CursorParams,
    filters: OrderFilter,
) -> PaginatedResponse[OrderRead]:
    qs = Order.filter(organization_id=org_id)
    qs = _apply_order_filters(qs, filters)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-updated_at", "-id"))
    order_reads = [OrderRead.model_validate(order) for order in items]
    return PaginatedResponse(items=order_reads, next_cursor=next_cursor, has_more=has_more)
```

- [ ] **Step 4: Verify types pass**

Run: `task mypy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/orders/service.py
git commit -m "feat(orders): add _apply_order_filters and update list functions"
```

---

### Task 3: Wire `OrderFilter` into router endpoints

**Files:**
- Modify: `app/orders/router.py`

- [ ] **Step 1: Update imports**

Replace the `OrderStatus` import — it's no longer needed directly in the router. Add `OrderFilter`:

```python
from app.orders.dependencies import OrderFilter, get_org_order_or_404, require_order_requester
```

Remove `from app.core.enums import OrderStatus` (no longer used in this file).

- [ ] **Step 2: Update `list_my_orders` endpoint**

Replace the current `list_my_orders` function (lines 30–38):

```python
@router.get("/orders/", response_model=PaginatedResponse[OrderRead])
async def list_my_orders(
    user: Annotated[User, Depends(require_active_user)],
    filters: Annotated[OrderFilter, Depends()],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[OrderRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_user_orders(user, params, filters)
```

- [ ] **Step 3: Update `list_org_orders` endpoint**

Replace the current `list_org_orders` function (lines 65–74):

```python
@router.get("/organizations/{org_id}/orders/", response_model=PaginatedResponse[OrderRead])
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

- [ ] **Step 4: Verify types pass**

Run: `task mypy`
Expected: PASS

- [ ] **Step 5: Run existing tests to ensure no regressions**

Run: `task test`
Expected: All existing order tests pass (the single `?status=pending` query string still works with multi-value param)

- [ ] **Step 6: Commit**

```bash
git add app/orders/router.py
git commit -m "feat(orders): wire OrderFilter into list endpoints"
```

---

### Task 4: Add filter tests

**Files:**
- Modify: `tests/db/test_orders.py`

- [ ] **Step 1: Add a second listing helper**

Add a helper function after the existing `_create_order` helper at the top of `tests/db/test_orders.py`. This creates a second listing for `listing_id` filter tests:

```python
async def _create_second_listing(
    client: AsyncClient,
    org_id: str,
    org_token: str,
    seed_categories: list[Any],
) -> str:
    """Create a second published listing in the same org. Returns listing_id."""
    resp = await client.post(
        f"/api/v1/organizations/{org_id}/listings/",
        json={
            "name": "Crane Liebherr LTM",
            "category_id": seed_categories[0].id,
            "price": 8000.00,
        },
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert resp.status_code == 201
    listing_id = resp.json()["id"]
    patch_resp = await client.patch(
        f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
        json={"status": "published"},
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert patch_resp.status_code == 200
    return listing_id
```

- [ ] **Step 2: Add `TestListOrdersFilters` class with multi-status test**

Add a new test class after the existing `TestListOrders` class (after line 787):

```python
@pytest.mark.anyio
class TestListOrdersFilters:
    async def test_filter_by_multiple_statuses(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        await _create_order(client, listing_id, renter_token)
        order2 = await _create_order(client, listing_id, renter_token, start_offset=10)

        # Offer order2 so it becomes "offered"
        start = _today() + timedelta(days=10)
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
            "/api/v1/orders/?status=pending&status=offered",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        statuses = {item["status"] for item in items}
        assert statuses == {"pending", "offered"}
```

- [ ] **Step 3: Run the new test**

Run: `pytest tests/db/test_orders.py::TestListOrdersFilters::test_filter_by_multiple_statuses -v`
Expected: PASS

- [ ] **Step 4: Add listing_id filter test**

Add to `TestListOrdersFilters`:

```python
    async def test_filter_by_listing_id(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        seed_categories: list[Any],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        listing2_id = await _create_second_listing(client, org_id, org_token, seed_categories)
        await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing2_id, renter_token, start_offset=10)

        resp = await client.get(
            f"/api/v1/orders/?listing_id={listing_id}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["listing_id"] == listing_id
```

Note: The `seed_categories` fixture is needed. Add the import `from app.listings.models import ListingCategory` if not already present at the top of the test file. Also add the `Any` import from `typing` if missing.

- [ ] **Step 5: Run the test**

Run: `pytest tests/db/test_orders.py::TestListOrdersFilters::test_filter_by_listing_id -v`
Expected: PASS

- [ ] **Step 6: Add date overlap filter tests**

Add to `TestListOrdersFilters`:

```python
    async def test_filter_by_date_range_overlap(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        # Order 1: starts in 1 day, ends in 5 days
        await _create_order(client, listing_id, renter_token, start_offset=1, duration=4)
        # Order 2: starts in 20 days, ends in 24 days
        await _create_order(client, listing_id, renter_token, start_offset=20, duration=4)

        # Filter for dates that only overlap with order 1
        date_from = (_today() + timedelta(days=1)).isoformat()
        date_to = (_today() + timedelta(days=3)).isoformat()
        resp = await client.get(
            f"/api/v1/orders/?date_from={date_from}&date_to={date_to}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1

    async def test_filter_by_date_from_only(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        # Order 1: starts in 1 day, ends in 5 days
        await _create_order(client, listing_id, renter_token, start_offset=1, duration=4)
        # Order 2: starts in 20 days, ends in 24 days
        await _create_order(client, listing_id, renter_token, start_offset=20, duration=4)

        # date_from after order 1 ends -> only order 2
        date_from = (_today() + timedelta(days=10)).isoformat()
        resp = await client.get(
            f"/api/v1/orders/?date_from={date_from}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
```

- [ ] **Step 7: Run the date tests**

Run: `pytest tests/db/test_orders.py::TestListOrdersFilters::test_filter_by_date_range_overlap tests/db/test_orders.py::TestListOrdersFilters::test_filter_by_date_from_only -v`
Expected: PASS

- [ ] **Step 8: Add search filter tests**

Add to `TestListOrdersFilters`:

```python
    async def test_search_by_order_id(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order1 = await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing_id, renter_token, start_offset=10)

        resp = await client.get(
            f"/api/v1/orders/?search={order1['id']}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == order1["id"]

    async def test_search_by_listing_name(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        seed_categories: list[Any],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        listing2_id = await _create_second_listing(client, org_id, org_token, seed_categories)
        await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing2_id, renter_token, start_offset=10)

        # "Excavator" matches "Excavator CAT 320" (first listing)
        resp = await client.get(
            "/api/v1/orders/?search=Excavator",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["listing_id"] == listing_id
```

- [ ] **Step 9: Run the search tests**

Run: `pytest tests/db/test_orders.py::TestListOrdersFilters::test_search_by_order_id tests/db/test_orders.py::TestListOrdersFilters::test_search_by_listing_name -v`
Expected: PASS

- [ ] **Step 10: Add combined filters test**

Add to `TestListOrdersFilters`:

```python
    async def test_combined_filters(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        seed_categories: list[Any],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        listing2_id = await _create_second_listing(client, org_id, org_token, seed_categories)
        await _create_order(client, listing_id, renter_token)
        order2 = await _create_order(client, listing2_id, renter_token, start_offset=10)

        # Offer order2
        start = _today() + timedelta(days=10)
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

        # Filter: status=offered + listing_id=listing2 -> should match order2 only
        resp = await client.get(
            f"/api/v1/orders/?status=offered&listing_id={listing2_id}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == order2["id"]
        assert items[0]["status"] == "offered"
```

- [ ] **Step 11: Add org endpoint filter test**

Add to `TestListOrdersFilters`:

```python
    async def test_org_orders_filter_by_listing_id(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        seed_categories: list[Any],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        listing2_id = await _create_second_listing(client, org_id, org_token, seed_categories)
        await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing2_id, renter_token, start_offset=10)

        resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/?listing_id={listing_id}",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["listing_id"] == listing_id
```

- [ ] **Step 12: Run the full test suite**

Run: `task test`
Expected: All tests pass, no regressions

- [ ] **Step 13: Run linting and type checks**

Run: `task ruff:fix && task mypy`
Expected: PASS

- [ ] **Step 14: Commit**

```bash
git add tests/db/test_orders.py
git commit -m "test(orders): add filter tests for status, listing_id, date range, search"
```
