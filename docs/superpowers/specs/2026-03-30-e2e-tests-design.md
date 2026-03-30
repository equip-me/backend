# E2E Test Suite — Design Spec

Comprehensive end-to-end tests covering all business logic of the rental platform. Tests exercise full user journeys across domain boundaries with real infrastructure (PostgreSQL, MinIO, Redis/ARQ, Dadata API). The only mock is date patching for order auto-transitions.

---

## Infrastructure

### Test Environment

All e2e tests run against real services from `docker-compose.test.yml`:
- **PostgreSQL** (port 5433) — test database
- **MinIO** (port 9002) — S3-compatible object storage
- **Redis** (port 6380) — ARQ job queue backend

**External API:**
- **Dadata** — real API calls. Key from `.env` locally, GitHub secret `DADATA_API_KEY` in CI.

### `tests/e2e/conftest.py`

- Override root conftest autouse mocks (`mock_dadata`, `mock_storage`, `mock_arq_pool`) — redefine as no-ops so real dependencies pass through
- **`mock_today`** helper — patches `datetime.date.today()` for order auto-transition testing (the only mock in e2e)
- **`@pytest.mark.e2e`** on all e2e tests — run via `pytest -m e2e` or exclude via `pytest -m "not e2e"`
- Reuse factory fixtures from root `conftest.py` (`client`, `create_user`, `create_organization`, etc.)
- Real INN for Dadata calls (e.g., Sberbank `7707083893`)

### CI Configuration

- Add `DADATA_API_KEY` as GitHub Actions secret
- Pass to test environment in CI workflow
- E2e tests run as a separate CI step: `pytest -m e2e`

---

## File Structure

```
tests/e2e/
├── conftest.py                    # Real dadata/storage/ARQ, date mocking, e2e mark
├── test_e2e_media.py              # Moved from tests/ (standalone media workflows)
├── test_user_registration.py      # 16 scenarios
├── test_org_lifecycle.py          # 32 scenarios
├── test_listing_catalog.py        # 25 scenarios
├── test_order_happy_path.py       # 26 scenarios
├── test_order_cancellations.py    # 16 scenarios
└── test_full_rental_journey.py    # 1 mega-scenario (21 steps)
```

**Total: ~116 e2e scenarios**

---

## Scenarios

### `test_user_registration.py` — User Registration & Auth (16 scenarios)

**Happy paths:**

1. **Full registration → login → profile** — register with valid data, login with same credentials, fetch `/users/me`, verify all fields
2. **Profile update** — update name, phone, email; verify changes persist
3. **Password change** — update password via `PATCH /users/me`, login with new password, confirm old password no longer works
4. **Public profile** — register user, fetch via `GET /users/{id}` without auth, verify public fields only
5. **Profile photo upload** — register, request upload URL for `user_profile` context, upload to MinIO, confirm, wait for processing → `ready`, verify photo attached to user profile
6. **Profile photo replacement** — upload a second photo, verify it replaces the first (old media record and S3 objects deleted)

**Negative / edge cases:**

7. **Duplicate email** — register, then register again with same email → 409
8. **Weak password variants** — no uppercase, no digit, too short → all rejected
9. **Invalid phone format** — non-Russian format → rejected
10. **Login with wrong password** → 401, generic message
11. **Login with non-existent email** → 401, same generic message (no info leak)
12. **Expired/invalid token** → 401
13. **Suspended user flow** — register, platform admin suspends via `/private/users/{id}/role`, then suspended user tries `/users/me` → 403
14. **Upload wrong media kind for profile** — e.g., `video` or `document` with `user_profile` context → rejected
15. **Upload photo by another user** — user A uploads, user B tries to confirm → 403
16. **Oversized file upload** — exceed file size limit → rejected

---

### `test_org_lifecycle.py` — Organization Lifecycle (32 scenarios)

**Happy paths:**

1. **Create organization** — authenticated user provides INN + contacts, real Dadata fills legal data, verify org created with status `created`, creator is `admin` `member`
2. **Org profile photo** — upload and attach profile photo to org, verify via org detail endpoint
3. **Update contacts** — `PUT` new contacts list, verify old contacts replaced
4. **Add payment details** — `POST` payment details, verify via `GET`
5. **Update payment details** — `POST` again with different bank info, verify upsert behavior
6. **Platform admin verifies org** — create org, admin calls `PATCH /private/organizations/{id}/verify`, verify status becomes `verified`
7. **Full setup journey** — create org → upload profile photo → add contacts → add payment details → verify → confirm org detail endpoint shows everything
8. **Invite member** — admin invites user with role `editor`, user accepts → status `member`, role `editor`
9. **Join request** — user sends join request → status `candidate`, admin approves with role `viewer` → status `member`
10. **Change member role** — admin changes member from `viewer` to `editor`, verify updated
11. **Remove member by admin** — admin removes a member, verify they lose access
12. **Member leaves voluntarily** — member removes themselves via `DELETE`
13. **List members** — create org with multiple members (admin, editor, viewer), verify list returns all

**Negative / edge cases:**

14. **Duplicate INN** → 409
15. **Invalid INN format** → rejected
16. **Missing contacts on creation** → validation error
17. **Invalid contact** (neither phone nor email) → rejected
18. **Non-authenticated creates org** → 401
19. **Non-admin tries to verify** → 403
20. **Non-admin updates contacts** → 403
21. **Non-admin adds payment details** → 403
22. **Org photo by non-admin** → 403
23. **Payment details when none set** → 404
24. **Unverified org listing visibility** — non-member → 403
25. **Editor tries to invite** → 403 (admin-only)
26. **Viewer tries to approve candidate** → 403
27. **Invite already-member user** → error (unique constraint on user+org)
28. **User accepts invite meant for someone else** → 403
29. **Approve a membership that's not in `candidate` status** → error
30. **Accept invitation that's not in `invited` status** → error
31. **Non-admin changes member role** → 403
32. **Non-admin removes another member** → 403 (only admin or self)

---

### `test_listing_catalog.py` — Listings & Categories (25 scenarios)

**Happy paths:**

1. **Create listing** — org editor creates listing, verify status `hidden`, all fields persisted
2. **Update listing** — change name, price, description, specifications, boolean flags; verify updates
3. **Publish listing** — change status `hidden` → `published`, verify visible in public catalog
4. **Hide listing** — `published` → `hidden`, verify disappears from public catalog
5. **Archive listing** — `published` → `archived`, verify gone from public catalog
6. **Delete listing** — editor deletes listing, verify 404 on fetch
7. **Listing with media** — create listing, upload photos and a video, confirm processing, verify media attached to listing detail
8. **Update listing media** — add more photos, delete one, verify updated media list
9. **Create org-specific category** — editor creates category for org, verify `verified=false`, visible in org category list
10. **Seed categories in public list** — verify global verified categories appear ordered by listing count
11. **Org category list includes global + org-specific** — verify both types returned
12. **Public catalog browsing** — create multiple listings across two verified orgs, browse with no filters, filter by `category_id`, filter by `organization_id`
13. **Listing detail public access** — fetch single published listing from verified org without auth

**Negative / edge cases:**

14. **Non-member creates listing** → 403
15. **Viewer creates listing** → 403 (editor+ required)
16. **Create listing in unverified org** — succeeds, but listing not visible in public catalog
17. **Non-member views listing from unverified org** → 403
18. **Member views listing from unverified org** — succeeds (any status)
19. **Create listing with non-existent category** → error
20. **Update listing from another org** → 403
21. **Delete listing from another org** → 403
22. **Status change by viewer** → 403
23. **Public catalog excludes hidden/archived listings** — verify only `published` from verified orgs
24. **Create category by viewer** → 403
25. **Public category list excludes unverified categories** — org-specific categories not in public list

---

### `test_order_happy_path.py` — Full Order Lifecycle (26 scenarios)

**Happy paths:**

1. **Complete rental journey: pending → offered → confirmed → active → finished** — renter creates order, org editor offers terms (adjusted cost and dates), renter confirms, mock date to start date → `active` + listing `in_rent`, mock date past end date → `finished` + listing `published`
2. **Order with original terms** — org offers same cost/dates as requested, renter confirms, verify `offered_*` fields match `requested_*`
3. **Re-offer before user decides** — org offers, then re-offers with different terms while still `offered`, renter confirms the updated terms
4. **Estimated cost calculation** — create order for 5 days at price 1000/day, verify `estimated_cost` = 5000.00
5. **Chained auto-transitions** — confirm order where both start and end dates are in the past (mock date), read → verify `confirmed → active → finished` in one read, listing ends at `published`
6. **List my orders (renter)** — renter places multiple orders, verify `GET /orders/` returns all
7. **List org orders** — org receives multiple orders, verify `GET /organizations/{org_id}/orders/` returns all
8. **Get order detail (both sides)** — renter via `/orders/{id}`, org via `/organizations/{org_id}/orders/{id}`, both see correct data

**Negative / edge cases:**

9. **Order for unpublished listing** — listing is `hidden` → rejected
10. **Order for listing from unverified org** → rejected
11. **Order with start date in the past** → rejected
12. **Order with start date after end date** → rejected
13. **Order for non-existent listing** → 404
14. **Unauthenticated user places order** → 401
15. **Offer with missing fields** — omit `offered_cost` or dates → validation error
16. **Offer with negative cost** → rejected
17. **Offer with start date after end date** → rejected
18. **Offer on wrong org's order** — editor from org B tries to offer on org A's order → 403
19. **Offer on already confirmed order** → invalid transition error
20. **Renter confirms order that's not `offered`** — e.g., still `pending` → invalid transition
21. **Non-requester tries to confirm** → 403
22. **Non-requester tries to decline** → 403
23. **Org editor tries to confirm** (user-only action) → 403
24. **Renter tries to offer** (org-only action) → 403
25. **Double confirm** — confirm an already confirmed order → invalid transition
26. **Actions on terminal statuses** — offer/confirm/cancel on `finished`, `rejected`, `declined` → all rejected

---

### `test_order_cancellations.py` — Cancel, Reject & Decline (16 scenarios)

**Happy paths:**

1. **Org rejects pending order** → `rejected` (terminal)
2. **User declines offered order** → `declined` (terminal)
3. **User cancels confirmed order** → `canceled_by_user`
4. **User cancels active order** — (mock date) → `canceled_by_user`, listing returns to `published`
5. **Org cancels confirmed order** → `canceled_by_organization`
6. **Org cancels active order** → `canceled_by_organization`, listing returns to `published`

**Negative / edge cases:**

7. **Reject non-pending order** — try to reject `offered` → invalid transition
8. **Decline non-offered order** — try to decline `pending` or `confirmed` → invalid transition
9. **User cancel from `pending`** → invalid transition
10. **User cancel from `offered`** → invalid transition (should decline instead)
11. **Org cancel from `pending`** → invalid transition (should reject instead)
12. **Org cancel from `offered`** → invalid transition
13. **Cancel already canceled order** → invalid transition
14. **Cancel finished order** → invalid transition
15. **Non-requester cancels** — different user tries user-cancel → 403
16. **Wrong org cancels** — editor from different org tries org-cancel → 403

---

### `test_full_rental_journey.py` — Mega E2E Scenario (1 test, 21 steps)

One large test that walks through the entire platform lifecycle as a real usage story:

1. **Renter registers** — full registration with profile photo upload
2. **Org owner registers** — separate user
3. **Org owner creates organization** — real Dadata, adds contacts
4. **Org owner adds payment details**
5. **Org owner uploads org profile photo**
6. **Platform admin verifies org**
7. **Org owner invites an editor** — editor registers, accepts invitation
8. **Editor creates a category** for the org
9. **Editor creates a listing** with photos and a video
10. **Editor publishes the listing** — verify it appears in public catalog
11. **Renter browses public catalog** — finds the listing, views detail with media
12. **Renter places an order** — verify estimated cost
13. **Editor offers adjusted terms** — different cost and dates
14. **Renter confirms the offer**
15. **Mock date to start date** — order becomes `active`, listing becomes `in_rent`
16. **Verify listing shows `in_rent`** in public catalog (or excluded)
17. **Mock date past end date** — order becomes `finished`, listing returns to `published`
18. **Renter places a second order** for the same listing
19. **Org editor rejects the second order**
20. **Renter places a third order, org offers, renter declines**
21. **Verify final state** — all three orders in expected statuses, listing is `published`, org members correct

---

### `test_e2e_media.py` — Standalone Media Workflows (moved from `tests/`)

Existing 5 tests, moved into `tests/e2e/`. Since the e2e conftest uses real storage and ARQ (instead of the mocks these tests were written against), the tests may need minor adjustments to work with real MinIO and Redis. Adapt as needed during implementation.

1. Photo upload → processing → retrieval
2. Video upload → processing → retrieval
3. Document upload → processing
4. Profile photo attachment
5. Processing failure scenarios
