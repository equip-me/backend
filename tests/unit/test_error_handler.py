import pytest
from fastapi import FastAPI
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
