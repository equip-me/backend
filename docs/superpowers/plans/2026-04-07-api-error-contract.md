# API Error Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add machine-readable error codes and interpolation params to every API error response, enabling frontend i18n and contextual error rendering.

**Architecture:** Extend `AppError` with `code` and `params` fields. Update `app_error_handler` to include them in the JSON response. Add a custom `RequestValidationError` handler for 422s. Migrate every raise site across all service/dependency modules to pass the new `code` (and `params` where applicable). Update WebSocket error frames to match. Existing tests that assert on error responses must be updated to match the new shape.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, Tortoise ORM, pytest

**Spec:** `docs/superpowers/specs/2026-04-07-api-error-contract-design.md`

**Python Conventions (for subagents):**
- No `# type: ignore` — fix the type error or restructure
- No `from __future__ import annotations` — Pydantic v2 and Tortoise need runtime types
- Strict mypy — every function fully typed, no implicit `Any`
- Ruff — line length 119, `select = ["ALL"]` with specific ignores
- All config in `pyproject.toml`
- Async everywhere
- httpx `AsyncClient` + `ASGITransport` for integration tests

---

### Task 1: Extend `AppError` with `code` and `params`

**Files:**
- Modify: `app/core/exceptions.py`
- Create: `tests/unit/test_exceptions.py`

- [ ] **Step 1: Write failing tests for the new error shape**

```python
# tests/unit/test_exceptions.py
from app.core.exceptions import (
    AccountSuspendedError,
    AlreadyExistsError,
    AppError,
    AppValidationError,
    ExternalServiceError,
    IDGenerationError,
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
)


class TestAppErrorCode:
    def test_default_code_is_empty_string(self) -> None:
        err = AppError("some detail")
        assert err.code == ""
        assert err.params == {}
        assert err.detail == "some detail"

    def test_code_and_params(self) -> None:
        err = AppError("some detail", code="test.error", params={"key": "val"})
        assert err.code == "test.error"
        assert err.params == {"key": "val"}

    def test_subclass_inherits_code(self) -> None:
        err = NotFoundError("not found", code="users.not_found")
        assert err.code == "users.not_found"
        assert err.params == {}

    def test_subclass_with_params(self) -> None:
        err = AppValidationError(
            "Cannot cancel order in status finished",
            code="orders.invalid_transition",
            params={"action": "cancel", "status": "finished"},
        )
        assert err.code == "orders.invalid_transition"
        assert err.params == {"action": "cancel", "status": "finished"}


class TestSubclassesAcceptCode:
    def test_not_found_error(self) -> None:
        err = NotFoundError("x", code="users.not_found")
        assert err.code == "users.not_found"

    def test_already_exists_error(self) -> None:
        err = AlreadyExistsError("x", code="users.email_taken")
        assert err.code == "users.email_taken"

    def test_invalid_credentials_error(self) -> None:
        err = InvalidCredentialsError("x", code="auth.invalid_credentials")
        assert err.code == "auth.invalid_credentials"

    def test_permission_denied_error(self) -> None:
        err = PermissionDeniedError("x", code="org.admin_required")
        assert err.code == "org.admin_required"

    def test_account_suspended_error(self) -> None:
        err = AccountSuspendedError("x", code="auth.account_suspended")
        assert err.code == "auth.account_suspended"

    def test_app_validation_error(self) -> None:
        err = AppValidationError("x", code="orders.start_date_in_past")
        assert err.code == "orders.start_date_in_past"

    def test_id_generation_error(self) -> None:
        err = IDGenerationError("x", code="server.internal_error")
        assert err.code == "server.internal_error"

    def test_external_service_error(self) -> None:
        err = ExternalServiceError("x", code="server.external_service_unavailable", params={"service": "dadata"})
        assert err.code == "server.external_service_unavailable"
        assert err.params == {"service": "dadata"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_exceptions.py -v`
Expected: FAIL — `AppError.__init__()` doesn't accept `code` or `params`

- [ ] **Step 3: Implement the changes to `AppError`**

Replace the `AppError` class in `app/core/exceptions.py` (lines 5-8):

```python
class AppError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        code: str = "",
        params: dict[str, str | int] | None = None,
    ) -> None:
        self.detail = detail
        self.code = code
        self.params: dict[str, str | int] = params or {}
        super().__init__(detail)
```

No changes needed to subclasses — they inherit `__init__` from `AppError`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_exceptions.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite to check nothing broke**

Run: `task test`
Expected: all existing tests still pass (since `code` and `params` have defaults, all existing raise sites are unchanged)

- [ ] **Step 6: Commit**

```bash
git add app/core/exceptions.py tests/unit/test_exceptions.py
git commit -m "feat(core): add code and params fields to AppError"
```

---

### Task 2: Update error handler and add 422 handler

**Files:**
- Modify: `app/core/exceptions.py` (handler function)
- Modify: `app/main.py` (register 422 handler)
- Create: `tests/unit/test_error_handler.py`

- [ ] **Step 1: Write failing tests for the new error response shape**

```python
# tests/unit/test_error_handler.py
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, field_validator

from app.core.exceptions import (
    AppError,
    AppValidationError,
    NotFoundError,
    PermissionDeniedError,
    app_error_handler,
    validation_error_handler,
)


def _make_app() -> FastAPI:
    """Minimal FastAPI app for testing error handlers."""
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.get("/not-found")
    async def _not_found() -> None:
        raise NotFoundError("User not found", code="users.not_found")

    @app.get("/with-params")
    async def _with_params() -> None:
        raise AppValidationError(
            "Cannot cancel order in status finished",
            code="orders.invalid_transition",
            params={"action": "cancel", "status": "finished"},
        )

    @app.get("/no-code")
    async def _no_code() -> None:
        raise PermissionDeniedError("Forbidden")

    class Body(BaseModel):
        email: str
        age: int

        @field_validator("email")
        @classmethod
        def must_contain_at(cls, v: str) -> str:
            if "@" not in v:
                msg = "Invalid email"
                raise ValueError(msg)
            return v

    @app.post("/validate")
    async def _validate(body: Body) -> Body:
        return body

    return app


@pytest.fixture
def app() -> FastAPI:
    return _make_app()


class TestAppErrorHandler:
    async def test_error_with_code(self, app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/not-found")
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == "users.not_found"
        assert body["detail"] == "User not found"
        assert body["params"] == {}

    async def test_error_with_params(self, app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/with-params")
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "orders.invalid_transition"
        assert body["params"] == {"action": "cancel", "status": "finished"}

    async def test_error_without_code_uses_empty_string(self, app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/no-code")
        assert resp.status_code == 403
        body = resp.json()
        assert body["code"] == ""
        assert body["detail"] == "Forbidden"
        assert body["params"] == {}


class TestValidationErrorHandler:
    async def test_422_response_shape(self, app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/validate", json={"email": "bad", "age": "not_int"})
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "validation.request_invalid"
        assert body["detail"] == "Request validation failed"
        assert body["params"] == {}
        assert isinstance(body["errors"], list)
        assert len(body["errors"]) >= 1
        first = body["errors"][0]
        assert "field" in first
        assert "code" in first
        assert "detail" in first
        assert "params" in first

    async def test_422_field_path(self, app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/validate", json={"email": "bad", "age": 10})
        body = resp.json()
        fields = [e["field"] for e in body["errors"]]
        assert "body.email" in fields
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_error_handler.py -v`
Expected: FAIL — `validation_error_handler` doesn't exist yet, response shape doesn't match

- [ ] **Step 3: Update `app_error_handler` in `app/core/exceptions.py`**

Replace the `app_error_handler` function (lines 55-57):

```python
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    status_code = _STATUS_MAP.get(type(exc), 500)
    return JSONResponse(
        status_code=status_code,
        content={"code": exc.code, "detail": exc.detail, "params": exc.params},
    )
```

- [ ] **Step 4: Add `validation_error_handler` in `app/core/exceptions.py`**

Add these imports at the top of `app/core/exceptions.py`:

```python
from fastapi.exceptions import RequestValidationError
```

Add the handler function after `app_error_handler`:

```python
async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        field = ".".join(str(part) for part in loc)
        errors.append({
            "field": field,
            "code": f"validation.{err.get('type', 'unknown')}",
            "detail": err.get("msg", ""),
            "params": {},
        })
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation.request_invalid",
            "detail": "Request validation failed",
            "params": {},
            "errors": errors,
        },
    )
```

Add the `Any` import at the top:

```python
from typing import Any
```

- [ ] **Step 5: Register the 422 handler in `app/main.py`**

Add import of `RequestValidationError` and `validation_error_handler`:

```python
from fastapi.exceptions import RequestValidationError

from app.core.exceptions import AppError, app_error_handler, validation_error_handler
```

After the existing `add_exception_handler` line (line 96), add:

```python
application.add_exception_handler(RequestValidationError, validation_error_handler)
```

Also update `_handle_app_error` (lines 68-72) to include the new response shape for the 500 fallback:

```python
async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, AppError):
        return await app_error_handler(request, exc)
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": "server.internal_error", "detail": "Internal server error", "params": {}},
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_error_handler.py -v`
Expected: all PASS

- [ ] **Step 7: Run full test suite**

Run: `task test`
Expected: some existing tests may fail because they assert `{"detail": "..."}` and now get `{"code": ..., "detail": ..., "params": ...}`. This is expected — we'll fix them in later tasks.

- [ ] **Step 8: Commit**

```bash
git add app/core/exceptions.py app/main.py tests/unit/test_error_handler.py
git commit -m "feat(core): structured error responses with code and params"
```

---

### Task 3: Add error codes to `auth` and `users` domains

**Files:**
- Modify: `app/core/dependencies.py` (auth errors)
- Modify: `app/users/service.py` (user service errors)

- [ ] **Step 1: Update `app/core/dependencies.py`**

Line 21-29 — `get_current_user`: all three `InvalidCredentialsError` raises get the same code:
```python
raise InvalidCredentialsError("Could not validate credentials", code="auth.invalid_credentials")
```

Line 36 — `require_active_user`:
```python
raise AccountSuspendedError("Account suspended", code="auth.account_suspended")
```

Line 44 — `require_platform_admin`:
```python
raise PermissionDeniedError("Platform admin access required", code="org.platform_admin_required")
```

Line 52 — `require_platform_owner`:
```python
raise PermissionDeniedError("Platform owner access required", code="org.platform_owner_required")
```

- [ ] **Step 2: Update `app/users/service.py`**

Line 26 — `register` duplicate email:
```python
raise AlreadyExistsError("User with this email already exists", code="users.email_taken")
```

Lines 47, 51 — `authenticate` wrong email/password:
```python
raise InvalidCredentialsError("Incorrect username or password", code="auth.incorrect_password")
```

Line 54 — `authenticate` suspended:
```python
raise AccountSuspendedError("Account suspended", code="auth.account_suspended")
```

Line 65 — `get_by_id`:
```python
raise NotFoundError("User not found", code="users.not_found")
```

Line 76 — `update_me` duplicate email:
```python
raise AlreadyExistsError("User with this email already exists", code="users.email_taken")
```

Line 80 — `update_me` wrong current password:
```python
raise InvalidCredentialsError("Incorrect username or password", code="auth.incorrect_password")
```

- [ ] **Step 3: Run ruff and mypy**

Run: `task ruff:fix && task mypy`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/core/dependencies.py app/users/service.py
git commit -m "feat(auth,users): add error codes to auth and users domains"
```

---

### Task 4: Add error codes to `org` domain

**Files:**
- Modify: `app/organizations/service.py`
- Modify: `app/organizations/dependencies.py`

- [ ] **Step 1: Update `app/organizations/dependencies.py`**

Line 22 — `get_org_or_404`:
```python
raise NotFoundError("Organization not found", code="org.not_found")
```

Line 36 — `require_org_member`:
```python
raise PermissionDeniedError("Organization membership required", code="org.membership_required")
```

Line 51 — `require_org_editor`:
```python
raise PermissionDeniedError("Organization editor access required", code="org.editor_required")
```

Line 66 — `require_org_admin`:
```python
raise PermissionDeniedError("Organization admin access required", code="org.admin_required")
```

- [ ] **Step 2: Update `app/organizations/service.py`**

Line 70 — duplicate INN:
```python
raise AlreadyExistsError("Organization with this INN already exists", code="org.inn_taken")
```

Line 84 — Dadata unavailable:
```python
raise ExternalServiceError("Dadata service unavailable", code="server.external_service_unavailable", params={"service": "dadata"})
```

Line 87 — org not found by INN:
```python
raise ExternalServiceError("Organization not found by INN", code="server.external_service_not_found", params={"service": "dadata"})
```

Lines 126, 346 — org not found:
```python
raise NotFoundError("Organization not found", code="org.not_found")
```

Line 190 — payment details not found:
```python
raise NotFoundError("Payment details not found", code="org.payment_details_not_found")
```

Line 214 — user not found for invite:
```python
raise NotFoundError("User not found", code="users.not_found")
```

Line 217 — already has membership (invite):
```python
raise AlreadyExistsError("User already has a membership in this organization", code="org.member_already_exists")
```

Line 233 — already has membership (join):
```python
raise AlreadyExistsError("You already have a membership in this organization", code="org.member_already_exists")
```

Line 248 — membership not found (approve):
```python
raise NotFoundError("Membership not found", code="org.membership_not_found")
```

Line 250 — not candidate:
```python
raise AppValidationError("Only candidates can be approved", code="org.not_candidate")
```

Line 261 — membership not found (accept invitation):
```python
raise NotFoundError("Membership not found", code="org.membership_not_found")
```

Line 265 — not own invitation:
```python
raise PermissionDeniedError("You can only accept your own invitation", code="org.not_own_invitation")
```

Line 267 — not invited:
```python
raise AppValidationError("Only invitations can be accepted", code="org.not_invited")
```

Line 290 — membership not found (change role):
```python
raise NotFoundError("Membership not found", code="org.membership_not_found")
```

Line 292 — not active member:
```python
raise AppValidationError("Can only change role of active members", code="org.not_active_member")
```

Line 294 — last admin (change role):
```python
raise AppValidationError("Cannot remove the last admin", code="org.last_admin")
```

Line 304 — membership not found (remove):
```python
raise NotFoundError("Membership not found", code="org.membership_not_found")
```

Line 319 — only admins can remove:
```python
raise PermissionDeniedError("Only admins can remove other members", code="org.cannot_remove_member")
```

Line 326 — last admin (remove):
```python
raise AppValidationError("Cannot remove the last admin", code="org.last_admin")
```

- [ ] **Step 3: Run ruff and mypy**

Run: `task ruff:fix && task mypy`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/organizations/service.py app/organizations/dependencies.py
git commit -m "feat(org): add error codes to organization domain"
```

---

### Task 5: Add error codes to `listings` domain

**Files:**
- Modify: `app/listings/service.py`
- Modify: `app/listings/dependencies.py`

- [ ] **Step 1: Update `app/listings/dependencies.py`**

Line 37 — listing not found (editor):
```python
raise NotFoundError("Listing not found", code="listings.not_found")
```

Line 47 — listing not found (public):
```python
raise NotFoundError("Listing not found", code="listings.not_found")
```

Line 51 — access denied (unverified org):
```python
raise PermissionDeniedError("Access denied", code="listings.access_denied")
```

Line 58 — not org member:
```python
raise PermissionDeniedError("Organization membership required", code="org.membership_required")
```

- [ ] **Step 2: Update `app/listings/service.py`**

Lines 90, 94 — category not found:
```python
raise NotFoundError("Category not found", code="listings.category_not_found")
```

Line 237 — organization not found:
```python
raise NotFoundError("Organization not found", code="org.not_found")
```

- [ ] **Step 3: Run ruff and mypy**

Run: `task ruff:fix && task mypy`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/listings/service.py app/listings/dependencies.py
git commit -m "feat(listings): add error codes to listings domain"
```

---

### Task 6: Add error codes to `orders` domain

**Files:**
- Modify: `app/orders/service.py`
- Modify: `app/orders/state_machine.py`
- Modify: `app/reservations/service.py`

- [ ] **Step 1: Update `app/orders/state_machine.py`**

Replace line 36-37:
```python
        msg = f"Cannot {action.value} order in status {current.value}"
        raise AppValidationError(msg)
```

With:
```python
        raise AppValidationError(
            f"Cannot {action.value} order in status {current.value}",
            code="orders.invalid_transition",
            params={"action": action.value, "status": current.value},
        )
```

- [ ] **Step 2: Update `app/orders/service.py`**

Line 60 — listing not found:
```python
raise NotFoundError("Listing not found", code="listings.not_found")
```

Line 63 — listing not available:
```python
raise AppValidationError("Listing is not available for ordering", code="orders.listing_unavailable")
```

Line 66 — org not verified:
```python
raise PermissionDeniedError("Organization is not verified", code="orders.org_not_verified")
```

Line 69 — start date in past:
```python
raise AppValidationError("requested_start_date cannot be in the past", code="orders.start_date_in_past")
```

Line 125 — no offered dates:
```python
raise AppValidationError("Cannot approve order without offered dates", code="orders.no_offered_dates")
```

- [ ] **Step 3: Update `app/reservations/service.py`**

Line 21 — overlap:
```python
raise AppValidationError(
    "Cannot approve: overlapping reservation exists for this listing",
    code="orders.reservation_overlap",
)
```

- [ ] **Step 4: Run ruff and mypy**

Run: `task ruff:fix && task mypy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/orders/service.py app/orders/state_machine.py app/reservations/service.py
git commit -m "feat(orders): add error codes to orders domain"
```

---

### Task 7: Add error codes to `media` domain

**Files:**
- Modify: `app/media/service.py`
- Modify: `app/media/dependencies.py`

- [ ] **Step 1: Update `app/media/dependencies.py`**

Line 17 — media not found:
```python
raise NotFoundError("Media not found", code="media.not_found")
```

Line 27 — not uploader:
```python
raise PermissionDeniedError("You can only manage your own uploads", code="media.not_uploader")
```

- [ ] **Step 2: Update `app/media/service.py`**

Line 48 — invalid content type:
```python
raise AppValidationError(
    f"Content type '{data.content_type}' is not allowed for {data.kind.value}",
    code="media.invalid_content_type",
    params={"content_type": data.content_type, "kind": data.kind.value},
)
```

Line 52 — file too large:
```python
raise AppValidationError(
    f"File size exceeds maximum of {max_size // (1024 * 1024)} MB for {data.kind.value}",
    code="media.file_too_large",
    params={"max_mb": max_size // (1024 * 1024), "kind": data.kind.value},
)
```

Line 57 — invalid filename:
```python
raise AppValidationError("Invalid filename", code="media.invalid_filename")
```

Line 89 — not pending upload:
```python
raise AppValidationError(
    f"Media is in '{media.status.value}' state, expected 'pending_upload'",
    code="media.not_pending_upload",
    params={"status": media.status.value},
)
```

Line 92 — upload missing:
```python
raise NotFoundError("Uploaded file not found in storage", code="media.upload_missing")
```

Line 149 — not failed:
```python
raise AppValidationError("Only failed media can be retried", code="media.not_failed")
```

For the media attachment validation helpers — there are several patterns in this file for limit exceeded, wrong kind, not ready, and not uploader. Each needs its specific code. Read the exact lines and apply:

- `media.limit_exceeded` with `params={"max": N, "kind": kind.value}` for max photos/videos/documents checks
- `media.wrong_kind` with `params={"id": str(media_id), "kind": actual_kind, "expected_kind": expected}` for kind mismatch
- `media.not_ready` with `params={"id": str(media_id)}` for status != READY checks
- `media.not_uploader` for uploaded_by != user checks in the service

The implementer MUST read the full `app/media/service.py` and locate every `raise` statement to apply the correct code. There are approximately 11 raise sites in this file.

- [ ] **Step 3: Run ruff and mypy**

Run: `task ruff:fix && task mypy`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/media/service.py app/media/dependencies.py
git commit -m "feat(media): add error codes to media domain"
```

---

### Task 8: Add error codes to `chat` domain

**Files:**
- Modify: `app/chat/service.py`
- Modify: `app/chat/dependencies.py`
- Modify: `app/chat/websocket.py`

- [ ] **Step 1: Update `app/chat/dependencies.py`**

Line 16 — order not found (user):
```python
raise NotFoundError("Order not found", code="orders.not_found")
```

Line 25 — not chat participant (user):
```python
raise PermissionDeniedError("Not a chat participant", code="chat.not_participant")
```

Line 32 — order not found (org):
```python
raise NotFoundError("Order not found", code="orders.not_found")
```

Line 47 — not org editor:
```python
raise PermissionDeniedError("Organization editor access required", code="org.editor_required")
```

- [ ] **Step 2: Update `app/chat/service.py`**

Line 133 — message empty:
```python
raise AppValidationError("Message must have text or attachments", code="chat.message_empty")
```

Line 135 — message too long:
```python
raise AppValidationError(
    f"Message exceeds maximum length of {settings.chat.max_message_length}",
    code="chat.message_too_long",
    params={"max_length": settings.chat.max_message_length},
)
```

Line 137 — too many attachments:
```python
raise AppValidationError(
    f"Maximum {settings.chat.max_attachments_per_message} attachments per message",
    code="chat.too_many_attachments",
    params={"max": settings.chat.max_attachments_per_message},
)
```

Line 146 — invalid media ID:
```python
raise AppValidationError(f"Invalid media ID: {mid}", code="chat.invalid_media_id", params={"id": mid})
```

Line 149 — media not found:
```python
raise NotFoundError(f"Media {mid} not found", code="chat.media_not_found", params={"id": mid})
```

Line 151 — media not ready:
```python
raise AppValidationError(f"Media {mid} is not ready", code="chat.media_not_ready", params={"id": mid})
```

Line 154 — media not yours:
```python
raise PermissionDeniedError(
    f"Media {mid} was not uploaded by you",
    code="chat.media_not_yours",
    params={"id": mid},
)
```

Line 201 — message not found:
```python
raise NotFoundError("Message not found", code="chat.message_not_found")
```

- [ ] **Step 3: Update WebSocket error frames in `app/chat/websocket.py`**

The WebSocket sends error frames in a different format (not via `AppError`). Update the inline error dicts to include `params`.

Line 129 — invalid JSON:
```python
await ws.send_json({"type": "error", "data": {"code": "chat.invalid_json", "detail": "Invalid JSON", "params": {}}})
```

Lines 136-141 — read only:
```python
await ws.send_json(
    {
        "type": "error",
        "data": {"code": "chat.read_only", "detail": "Chat is read-only", "params": {}},
    }
)
```

Lines 144-149 — rate limited:
```python
settings = get_settings()
await ws.send_json(
    {
        "type": "error",
        "data": {
            "code": "chat.rate_limited",
            "detail": "Too many messages, slow down",
            "params": {"limit": settings.chat.rate_limit_per_minute, "window_seconds": 60},
        },
    }
)
```

Lines 158-164 — catch-all for `send_message` exceptions. Now that service-layer exceptions carry `code` and `params`, forward them:
```python
except AppError as exc:
    await ws.send_json(
        {
            "type": "error",
            "data": {"code": exc.code, "detail": exc.detail, "params": exc.params},
        }
    )
except Exception as exc:  # noqa: BLE001
    await ws.send_json(
        {
            "type": "error",
            "data": {"code": "chat.validation_error", "detail": str(exc), "params": {}},
        }
    )
```

This requires adding the import at the top of `websocket.py`:
```python
from app.core.exceptions import AppError
```

- [ ] **Step 4: Run ruff and mypy**

Run: `task ruff:fix && task mypy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/chat/service.py app/chat/dependencies.py app/chat/websocket.py
git commit -m "feat(chat): add error codes to chat domain"
```

---

### Task 9: Add error codes to remaining raise sites

**Files:**
- Modify: `app/core/identifiers.py` (IDGenerationError)
- Any other files with raise sites not yet covered

- [ ] **Step 1: Search for remaining uncoded raise sites**

Run: `grep -rn "raise.*Error(" app/ --include="*.py" | grep -v "code="`

Identify any `raise` statements that don't yet include `code=`. Fix each one.

For `IDGenerationError` in `app/core/identifiers.py`:
```python
raise IDGenerationError("...", code="server.internal_error")
```

- [ ] **Step 2: Run ruff and mypy**

Run: `task ruff:fix && task mypy`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add -u
git commit -m "feat(core): add error codes to remaining raise sites"
```

---

### Task 10: Fix existing tests for new error response shape

**Files:**
- Modify: all test files under `tests/` that assert on error response bodies

- [ ] **Step 1: Run full test suite and collect failures**

Run: `task test`

Collect all test failures. Most will be tests asserting `resp.json() == {"detail": "..."}` or `resp.json()["detail"]` without expecting `code` and `params`.

- [ ] **Step 2: Update test assertions**

For each failing test, update the assertion to match the new shape. Two patterns:

**Pattern A** — tests that check the full response body:
```python
# Before:
assert resp.json() == {"detail": "User not found"}

# After:
assert resp.json()["code"] == "users.not_found"
assert resp.json()["detail"] == "User not found"
```

**Pattern B** — tests that check only `detail`:
```python
# Before:
assert resp.json()["detail"] == "User not found"

# After (no change needed — detail still exists):
assert resp.json()["detail"] == "User not found"
# Optionally also assert the code:
assert resp.json()["code"] == "users.not_found"
```

**Pattern C** — 422 validation tests:
```python
# Before:
assert resp.status_code == 422
assert resp.json()["detail"][0]["msg"] == "..."

# After:
assert resp.status_code == 422
assert resp.json()["code"] == "validation.request_invalid"
assert resp.json()["errors"][0]["detail"] == "..."
```

The implementer MUST run the full suite, read each failure, and update accordingly. Do NOT blindly replace — check what each test is actually asserting.

- [ ] **Step 3: Run full test suite to confirm green**

Run: `task test`
Expected: all PASS

- [ ] **Step 4: Run ruff and mypy**

Run: `task ruff:fix && task mypy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -u
git commit -m "test: update assertions for structured error responses"
```

---

### Task 11: Final validation

- [ ] **Step 1: Run the full CI pipeline locally**

Run: `task ci`
Expected: ruff + mypy + all tests PASS

- [ ] **Step 2: Verify error response shape manually**

Run the dev server and trigger a few errors to verify the response shape:

```bash
# Start server
task dev &

# 401 — invalid token
curl -s localhost:8000/api/v1/users/me -H "Authorization: Bearer invalid" | python -m json.tool

# 422 — validation error
curl -s -X POST localhost:8000/api/v1/users/register -H "Content-Type: application/json" -d '{"email": "bad"}' | python -m json.tool
```

Verify both return the new shape with `code`, `detail`, `params` (and `errors` for 422).

- [ ] **Step 3: Commit any final fixes**

If any issues found, fix and commit.
