# Order Filtering & Search

## Summary

Add filtering and search to order list endpoints (`GET /orders/` and `GET /organizations/{org_id}/orders/`), following the pattern established for listings in PR #52.

## Current State

Both order list endpoints support only:
- Cursor-based pagination (`cursor`, `limit`)
- Single `status` enum filter

## Changes

### OrderFilter dependency class

New class in `app/orders/dependencies.py` using FastAPI `Query()` params, injected via `Depends()`:

| Param | Type | Description |
|-------|------|-------------|
| `status` | `list[OrderStatus] \| None` | Multi-value status filter (`?status=pending&status=offered`). Replaces current single-value param. |
| `listing_id` | `str \| None` | Filter orders for a specific listing |
| `date_from` | `date \| None` | Orders whose requested date range overlaps on or after this date |
| `date_to` | `date \| None` | Orders whose requested date range overlaps on or before this date |
| `search` | `str \| None` | Case-insensitive search on order ID and listing name (via join) |

All params are optional. When omitted, no filtering is applied.

### Date overlap logic

An order with `[requested_start_date, requested_end_date]` overlaps filter range `[date_from, date_to]` when both:
- `requested_end_date >= date_from` (order doesn't end before range starts)
- `requested_start_date <= date_to` (order doesn't start after range ends)

Each condition is applied independently — providing only `date_from` means "orders not ending before this date".

### Filter application

New `_apply_order_filters()` helper in `app/orders/service.py`:
- `statuses` -> `status__in`
- `listing_id` -> `listing_id` exact match
- `date_from` -> `requested_end_date__gte`
- `date_to` -> `requested_start_date__lte`
- `search` -> `Q(id__icontains=...) | Q(listing__name__icontains=...)`

Applied in both `list_user_orders()` and `list_org_orders()`.

### Route changes

Both endpoints replace the standalone `status: OrderStatus | None` query param with `filters: Annotated[OrderFilter, Depends()]`. The `OrderFilter` class produces the query params — no separate param declarations needed.

### Breaking change

`status` moves from single-value to multi-value (`list[OrderStatus]`). Single-value usage (`?status=pending`) still works, so existing clients are unaffected.

## Files to modify

| File | Change |
|------|--------|
| `app/orders/dependencies.py` | Add `OrderFilter` class |
| `app/orders/service.py` | Add `_apply_order_filters()`, update `list_user_orders()` and `list_org_orders()` signatures |
| `app/orders/router.py` | Replace `status` param with `OrderFilter` dependency on both list endpoints |
| `tests/` | Add filter test cases (per-filter and combined) |

## Testing

Test cases for each filter individually and in combination:
- Multi-value status filtering
- Listing ID filtering
- Date overlap: orders fully inside, partially overlapping, and outside the range
- Search by order ID substring
- Search by listing name substring
- Combined filters (e.g., status + listing_id + date range)

## Out of scope

- Cost range filters
- Separate nested route for listing orders (`/organizations/{org_id}/listings/{listing_id}/orders/`)
- Sorting options beyond current `(-updated_at, -id)`
