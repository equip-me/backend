# Organization Business Logic — Design Spec

## Scope

Implement the full Organization section (Section 3) from `docs/business-logic.md`:
organization CRUD, contacts management, payment details, membership system, Dadata integration, and verification.

## Decisions

- **Single module:** all org logic in `app/organizations/` (schemas, service, router, dependencies)
- **Dadata client:** `dadata-py` library, injected via FastAPI dependency (`get_dadata_client`)
- **Membership endpoints:** `approve` (admin approves candidate) and `accept` (user accepts invite) are separate endpoints
- **Candidate approval:** admin provides role in the approve request body
- **Contact model change:** replace `employee_name`, `employee_middle_name`, `employee_surname` with a single required `display_name` field (supports both person names and department names like "Rental Department")

## File Structure

### New files

```
app/organizations/
  schemas.py          # Pydantic request/response models
  service.py          # Business logic
  router.py           # API endpoints
  dependencies.py     # Org-level permission dependencies
```

### Modified files

- `app/main.py` — register organizations router
- `app/core/exceptions.py` — add `ExternalServiceError` (502)
- `app/organizations/models.py` — replace contact name fields with `display_name`
- `docs/business-logic.md` — update contact model to use `display_name`
- `tests/conftest.py` — add org-related fixtures
- `pyproject.toml` / `poetry.lock` — add `dadata` dependency

### New test file

- `tests/test_organizations.py`

## Dependencies (org-level)

`app/organizations/dependencies.py` provides three FastAPI dependencies that take `org_id` from the path and the current user from `require_active_user`:

- `require_org_member(org_id, user)` — any role, status=`member`. Returns `Membership`.
- `require_org_editor(org_id, user)` — role `admin` or `editor`, status=`member`. Returns `Membership`.
- `require_org_admin(org_id, user)` — role `admin`, status=`member`. Returns `Membership`.

All three verify the org exists (404 if not) and raise 403 on insufficient permissions.

## Schemas

### Organization

- `OrganizationCreate`: `inn: str` (regex `^\d{10}$|^\d{12}$`), `contacts: list[ContactCreate]` (min 1)
- `ContactCreate`: `display_name: str`, `phone: str | None`, `email: EmailStr | None` + validator: at least one of phone/email
- `ContactRead`: `id: UUID`, `display_name`, `phone`, `email`
- `OrganizationRead`: all org model fields + `contacts: list[ContactRead]`

### Payment Details

- `PaymentDetailsCreate`: `payment_account`, `bank_bic`, `bank_inn`, `bank_name`, `bank_correspondent_account` (all required strings)
- `PaymentDetailsRead`: same + `id: UUID`

### Membership

- `MembershipInvite`: `user_id: str`, `role: MembershipRole`
- `MembershipApprove`: `role: MembershipRole`
- `MembershipRoleUpdate`: `role: MembershipRole`
- `MembershipRead`: `id: UUID`, `user_id: str`, `organization_id: str`, `role`, `status`, `created_at`, `updated_at`

## API Endpoints

### Organization CRUD

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/organizations/` | Authenticated | Create org with contacts (Dadata + creator becomes admin) |
| GET | `/organizations/{org_id}` | Public | Get org by ID (includes contacts) |
| GET | `/users/me/organizations` | Authenticated | List current user's organizations |
| PATCH | `/private/organizations/{org_id}/verify` | Platform Admin | Verify organization |

### Contacts & Payments

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| PUT | `/organizations/{org_id}/contacts` | Org Admin | Replace all contacts (transactional) |
| GET | `/organizations/{org_id}/payment-details` | Org Member | Get payment details (404 if not set) |
| POST | `/organizations/{org_id}/payment-details` | Org Admin | Create or replace payment details |

### Membership

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/organizations/{org_id}/members/invite` | Org Admin | Invite user for a role |
| POST | `/organizations/{org_id}/members/join` | Authenticated | Request to join |
| PATCH | `/organizations/{org_id}/members/{member_id}/approve` | Org Admin | Approve candidate (role in body) |
| PATCH | `/organizations/{org_id}/members/{member_id}/accept` | Authenticated (invited user) | Accept invitation |
| PATCH | `/organizations/{org_id}/members/{member_id}/role` | Org Admin | Change member role |
| DELETE | `/organizations/{org_id}/members/{member_id}` | Org Admin or Self | Remove/cancel/decline |
| GET | `/organizations/{org_id}/members` | Org Member | List members |

## Service Logic

### Organization Creation (transactional)

1. Validate INN format and contacts
2. Call `dadata.find_by_id("party", inn)` — failure or empty → 502 `ExternalServiceError`
3. In a single transaction:
   - Create `Organization` with Dadata-extracted fields + full `dadata_response`
   - Create `OrganizationContact` records
   - Create `Membership` (creator, role=`admin`, status=`member`)
4. Return org with contacts

Dadata field mapping:

| Dadata field path | Maps to |
|-------------------|---------|
| `data.name.short_with_opf` | `short_name` |
| `data.name.full_with_opf` | `full_name` |
| `data.inn` | `inn` |
| `data.state.registration_date` | `registration_date` |
| `data.address.value` | `legal_address` |
| `data.management.name` | `manager_name` |
| `data.okved` | `main_activity` |

### Contacts Replacement (transactional)

Within a single `in_transaction()`:
1. Delete all existing contacts for the org
2. Create new contacts from request body
3. Validate: at least one contact, each with `display_name` + at least one of phone/email

### Payment Details

Upsert: if `PaymentDetails` exists for the org, update all fields. Otherwise, create.

### Membership Rules

- **Invite:** Target user must exist (404). No existing membership for user+org (409). Create with status=`invited`, role from request.
- **Join:** No existing membership (409). Create with status=`candidate`, role=`viewer` (placeholder).
- **Approve:** Status must be `candidate` (400). Set role from body, status → `member`.
- **Accept:** Caller must be the invited user (403). Status must be `invited` (400). Status → `member`.
- **Role change:** Status must be `member` (400). Cannot demote last admin (400).
- **Delete:** Self-removal or admin-removal. Last admin cannot leave (400).

### Verification

Platform admin sets status `created` → `verified`. Idempotent.

## Error Handling

| Scenario | Status | Error type |
|----------|--------|------------|
| Dadata unreachable / error | 502 | `ExternalServiceError` |
| Dadata empty results | 502 | `ExternalServiceError` |
| Duplicate INN | 409 | `AlreadyExistsError` |
| Org not found | 404 | `NotFoundError` |
| Invalid INN format | 422 | Pydantic validation |
| No contacts / invalid contacts | 422 | Pydantic validation |
| Insufficient org permission | 403 | `PermissionDeniedError` |
| Duplicate membership | 409 | `AlreadyExistsError` |
| Wrong membership status | 400 | `AppValidationError` |
| Accept by wrong user | 403 | `PermissionDeniedError` |
| Last admin cannot leave/be demoted | 400 | `AppValidationError` |

## Testing

**Mocking:** Dadata is always mocked via dependency override.

**New fixtures:** `create_organization` helper, `dadata_mock` fixture.

**Coverage areas:**

- Organization CRUD: create (happy + Dadata failure + duplicate INN + invalid contacts), get, list user's orgs, verify
- Contacts: replace (happy + transactional + empty list + non-admin)
- Payment details: create, upsert, non-admin
- Membership: invite→approve, join→approve, accept invite, duplicate membership, wrong status, wrong user on accept, self-removal, admin removal, last admin protection, role change, list members
