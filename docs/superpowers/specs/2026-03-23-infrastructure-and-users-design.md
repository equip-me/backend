# Infrastructure + Users Domain — Design Spec

**Date:** 2026-03-23
**Scope:** Full project infrastructure scaffold + Users domain (complete business logic, routes, tests). All other domains (Organizations, Memberships, Listings, Orders) get model definitions only — business logic comes in future sessions.

---

## 1. Decisions

| Decision | Choice |
|----------|--------|
| Build order | Infrastructure-heavy start, stop at Users |
| Code organization | Domain-package style (`app/users/`, `app/organizations/`, etc.) |
| Business logic layer | Service layer: `router → service → ORM` |
| Error handling | Domain exceptions + centralized FastAPI exception handler |
| Auth dependencies | `get_current_user`, `require_active_user`, `require_platform_admin`, `require_platform_owner` (separate) |
| Registration response | Returns token immediately (no separate login step) |

---

## 2. Project Skeleton & Infrastructure

### 2.1 Root Files

```
pyproject.toml              # Poetry deps, ruff/mypy/pytest config
poetry.lock                 # Pinned deps (committed)
Taskfile.yml                # go-task commands (from tech spec verbatim)
docker-compose.yml          # Dev PostgreSQL only
docker-compose.prod.yml     # Prod: db + app (gunicorn + uvicorn workers)
Dockerfile                  # Multi-stage, python:3.13-slim, APP_VERSION build arg
.pre-commit-config.yaml     # lint:fix + mypy pre-commit, pytest pre-push
.env.example                # Template for required env vars
```

### 2.2 Config Files

```
config/
  base.yaml                 # Shared defaults (db host/port, cors, jwt settings including token_lifetime_days)
  dev.yaml                  # Dev overrides (localhost DB, CORS for localhost:3000/5173)
  test.yaml                 # Test overrides (separate test DB name)
  prod.yaml                 # Prod overrides (strict CORS origins)
```

### 2.3 Dependencies

**Runtime:**

- `fastapi` (≥ 0.135.2)
- `uvicorn` (≥ 0.42.0)
- `pydantic` (≥ 2.12.5)
- `pydantic-settings` (≥ 2.13.1)
- `pyyaml`
- `tortoise-orm[asyncpg]` (≥ 1.1.7)
- `argon2-cffi`
- `pyjwt`
- `dadata` (≥ 25.10.0)
- `httpx` (≥ 0.28.1)
- `gunicorn` (≥ 25.1.0)

**Dev:**

- `pytest`
- `pytest-cov` (≥ 7.1.0)
- `anyio`
- `ruff` (≥ 0.15.7)
- `mypy`
- `pre-commit`

### 2.4 Config Loader (`app/core/config.py`)

Uses `pydantic-settings` with a custom YAML settings source. Loads `base.yaml`, deep-merges the env-specific file selected by `APP_ENV` (default: `dev`). Secrets come exclusively from environment variables:

- `DATABASE_PASSWORD`
- `JWT_SECRET`
- `DADATA_API_KEY`

---

## 3. Application Core (`app/core/`)

```
app/
  __init__.py
  main.py                    # FastAPI app, lifespan, CORS, exception handlers, router includes
  core/
    __init__.py
    config.py                # Settings class, YAML loader
    database.py              # Tortoise ORM config dict, init/shutdown helpers, model discovery
    enums.py                 # All domain enums (str, Enum)
    security.py              # Argon2id hash/verify, JWT encode/decode
    dependencies.py          # FastAPI Depends: auth + permission checks
    exceptions.py            # Domain exceptions + centralized handler
```

### 3.1 Enums (`app/core/enums.py`)

All are `str, Enum` for Pydantic serialization:

- `UserRole`: `owner`, `admin`, `user`, `suspended`
- `OrganizationStatus`: `created`, `verified`
- `MembershipRole`: `admin`, `editor`, `viewer`
- `MembershipStatus`: `candidate`, `invited`, `member`
- `ListingStatus`: `hidden`, `published`, `in_rent`, `archived`
- `OrderStatus`: `pending`, `offered`, `rejected`, `confirmed`, `declined`, `active`, `finished`, `canceled_by_user`, `canceled_by_organization`

### 3.2 Exceptions (`app/core/exceptions.py`)

```python
class AppError(Exception):
    """Base domain exception."""
    def __init__(self, detail: str) -> None: ...

class NotFoundError(AppError): ...
class AlreadyExistsError(AppError): ...
class InvalidCredentialsError(AppError): ...
class PermissionDeniedError(AppError): ...
class AccountSuspendedError(AppError): ...
class AppValidationError(AppError): ...
```

Named `AppValidationError` (not `ValidationError`) to avoid import clashes with Pydantic's `ValidationError`.

Centralized handler registered in `main.py`:

| Exception | HTTP Status |
|-----------|-------------|
| `NotFoundError` | 404 |
| `AlreadyExistsError` | 409 |
| `InvalidCredentialsError` | 401 |
| `PermissionDeniedError` | 403 |
| `AccountSuspendedError` | 403 |
| `AppValidationError` | 422 |

**Error detail strings** must match the business spec where it defines them (see `business-logic.md` §2.4). Other `AppError` subclasses use descriptive messages at the implementer's discretion:

| Exception | `detail` value |
|-----------|---------------|
| `InvalidCredentialsError` (login) | `"Incorrect username or password"` |
| `InvalidCredentialsError` (bad token) | `"Could not validate credentials"` |
| `AccountSuspendedError` | `"Account suspended"` |

### 3.3 Security (`app/core/security.py`)

- `hash_password(password: str) → str` — Argon2id
- `verify_password(plain: str, hashed: str) → bool` — Argon2id verify
- `create_access_token(subject: str) → str` — JWT HS256, `sub` = user ID (UUID string), `exp` = now + `jwt.token_lifetime_days` from YAML config (default: 7 in `base.yaml`, overridable per environment)
- `decode_access_token(token: str) → str` — returns `sub` (user ID), raises on expired/invalid

### 3.4 Dependencies (`app/core/dependencies.py`)

1. `get_current_user` — extracts Bearer token, decodes JWT, fetches User by ID. Raises `InvalidCredentialsError` on bad/expired token or user not found.
2. `require_active_user` — wraps `get_current_user`, checks `role != suspended`. Raises `AccountSuspendedError`.
3. `require_platform_admin` — wraps `require_active_user`, checks `role in (admin, owner)`. Raises `PermissionDeniedError`.
4. `require_platform_owner` — wraps `require_active_user`, checks `role == owner`. Raises `PermissionDeniedError`.

### 3.5 App Lifespan (`main.py`)

- **Startup:** load config → init Tortoise (connect) → seed listing categories if DB empty
- **Shutdown:** close Tortoise connections

**Schema management:** Tortoise migrations (`tortoise makemigrations` / `migrate`) are the source of truth in all environments. `generate_schemas=True` is used **only** in the test `conftest.py` fixture for convenience (ephemeral test DB, recreated each session). Dev and prod always use migrations.
- CORS middleware configured from YAML settings
- Exception handlers registered for all `AppError` subclasses

---

## 4. DB Models (All Domains Scaffolded)

All models use UUID PKs (`fields.UUIDField(pk=True)`). Fields follow `docs/business-logic.md` exactly.

### 4.1 File Layout

```
app/
  users/
    __init__.py
    models.py              # User
  organizations/
    __init__.py
    models.py              # Organization, Membership
  listings/
    __init__.py
    models.py              # Listing, ListingCategory
  orders/
    __init__.py
    models.py              # Order
```

### 4.2 Model Summaries

**User** — email (unique), hashed_password, phone, name, middle_name (nullable), surname, role (default `user`), created_at.

**Organization** — inn (unique, required), contact_phone (required), contact_email (required), contact_employee_name (required), status (default `created`). Nullable fields: short_name, full_name, ogrn, kpp, registration_date, authorized_capital_k_rubles, legal_address, manager_name, main_activity, contact_employee_middle_name, contact_employee_surname.

**Membership** — FK user, FK organization, role, status, created_at, updated_at. Unique constraint: `(user, organization)`.

**ListingCategory** — name, FK organization (nullable), FK added_by (nullable), created_at, verified (default `false`).

**Listing** — name, FK category, price, description (nullable), specifications (JSON, nullable), status (default `hidden`), FK organization (cascade delete), FK added_by, with_operator, on_owner_site, delivery, installation, setup (all boolean, default `false`), created_at, updated_at.

**Order** — FK listing, FK organization, FK requester, requested_start_date, requested_end_date, status (default `pending`), estimated_cost (nullable), offered_cost (nullable), offered_start_date (nullable), offered_end_date (nullable), created_at, updated_at.

Only the Users domain gets services, routers, and tests in this iteration. All other domains are model-only stubs.

---

## 5. Users Domain (Fully Implemented)

### 5.1 Schemas (`app/users/schemas.py`)

- **`UserCreate`** — email, password, phone, name, surname, middle_name (optional). Validators: email format, Russian mobile phone regex, password strength (8+ chars, at least one lowercase [Latin a-z or Cyrillic а-я], one uppercase [Latin A-Z or Cyrillic А-Я], one digit).
- **`UserUpdate`** — patchable fields: email, phone, name, surname, middle_name (all optional). Email change must pass format validation and uniqueness check. Password change: `password` (current) + `new_password` pair. `new_password` must pass the same strength validators as registration (8+ chars, upper, lower, digit). Both `password` and `new_password` must be provided together — `password` without `new_password` is an error, and `new_password` without `password` is also an error.
- **`UserRead`** — id, email, phone, name, middle_name, surname, role, created_at. Never exposes `hashed_password`.
- **`UserRoleUpdate`** — role field.
- **`LoginRequest`** — email, password.
- **`TokenResponse`** — access_token, token_type.

### 5.2 Service (`app/users/service.py`)

- `register(data: UserCreate) → TokenResponse` — duplicate email check (raises `AlreadyExistsError`), hash password, create user, generate JWT, return token. Registration returns a token so the user is immediately logged in.
- `authenticate(email: str, password: str) → TokenResponse` — fetch by email, verify password. If user is `suspended`, raises `AccountSuspendedError` (403, `"Account suspended"`) — no token is issued. For wrong email or wrong password, raises `InvalidCredentialsError` (401, `"Incorrect username or password"`) — same message for both, no information leak.
- `get_by_id(user_id: UUID) → User` — raises `NotFoundError`.
- `update_me(user: User, data: UserUpdate) → User` — partial update. Password change requires current password verification.
- `change_role(user_id: UUID, new_role: UserRole, acting_user: User) → User` — platform admin/owner action. **Role escalation rule:** assigning `admin` or `owner` role requires the acting user to be `owner`. Platform `admin` can only assign `user` or `suspended` roles. Raises `PermissionDeniedError` if an admin tries to assign `admin`/`owner`.

### 5.3 Router (`app/users/router.py`)

| Method | Path | Dependency | Service Call |
|--------|------|------------|-------------|
| POST | `/users/` | None (public) | `register` |
| POST | `/users/token` | None (public) | `authenticate` |
| GET | `/users/me` | `require_active_user` | return current user |
| PATCH | `/users/me` | `require_active_user` | `update_me` |
| GET | `/users/{user_id}` | None (public) | `get_by_id` |
| PATCH | `/private/users/{user_id}/role` | `require_platform_admin` | `change_role` |

Route registration order: `/users/me` before `/users/{user_id}` to prevent "me" matching as a UUID.

---

## 6. Tests

### 6.1 File Layout

```
tests/
  __init__.py
  conftest.py              # Shared fixtures
  test_users.py            # Users domain tests
```

### 6.2 Fixtures (`conftest.py`)

- `initialize_db` (session-scoped, autouse) — inits Tortoise against test DB (from `test.yaml`), generates schemas, tears down after session.
- `truncate_tables` (function-scoped, autouse) — truncates all tables between tests.
- `client` — `httpx.AsyncClient` with `ASGITransport` pointed at the FastAPI app.
- `create_user(...)` — factory helper that registers a user and returns `UserRead` + token. Accepts overrides.
- `admin_user` / `owner_user` — pre-built fixtures with elevated roles.

### 6.3 Test Cases (`test_users.py`)

All tests are async (`@pytest.mark.anyio`), integration-style (HTTP through `AsyncClient`).

**Registration:**
- Happy path — returns token, token works for `/users/me`
- Duplicate email → 409
- Weak password → 422
- Invalid phone → 422
- Invalid email → 422

**Login:**
- Happy path — returns token
- Wrong email → 401
- Wrong password → 401 (same message as wrong email)

**GET /users/me:**
- Valid token → user profile
- Expired/invalid token → 401
- Suspended user → 403

**PATCH /users/me:**
- Update name
- Update phone
- Password change happy path (both `password` + `new_password` provided)
- Partial pair: only `new_password` without `password` → error
- Partial pair: only `password` without `new_password` → error
- Password change with wrong current password → error
- Weak `new_password` with valid current password → 422

**GET /users/{user_id}:**
- Existing user → profile
- Non-existent UUID → 404

**PATCH /private/users/{user_id}/role:**
- Admin assigns `user`/`suspended` role → success
- Non-admin → 403
- Admin tries to assign `admin` or `owner` role → 403 (escalation denied)
- Owner assigns `admin` role → success
- Owner assigns any role → success

**Login (suspended):**
- Suspended user with correct password → 403 `"Account suspended"`

---

## 7. Out of Scope (Future Sessions)

- Organizations domain (service, router, tests)
- Memberships domain (service, router, tests)
- Listings domain (service, router, tests, category seeding logic)
- Orders domain (service, router, tests, state machine)
- Dadata integration (org creation auto-fill)
- Per-order chat
- Automatic order status transitions (scheduled jobs)
