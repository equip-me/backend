import inspect
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from app.observability.context import RequestContext, request_context
from app.observability.events import emit_event
from app.observability.logs import RequestContextFilter
from app.observability.middleware import TraceIDMiddleware
from app.observability.tracing import _extract_span_attributes, traced


async def test_extract_string_id_params() -> None:
    async def sample_func(org_id: str, member_id: str) -> None: ...

    sig = inspect.signature(sample_func)
    attrs = _extract_span_attributes(sig, ("org-123", "mem-456"), {})
    assert attrs == {"app.org_id": "org-123", "app.member_id": "mem-456"}


async def test_extract_model_objects() -> None:
    class FakeUser:
        id: str = "usr-abc"

    async def sample_func(user: FakeUser) -> None: ...

    sig = inspect.signature(sample_func)
    attrs = _extract_span_attributes(sig, (FakeUser(),), {})
    assert attrs == {"app.user_id": "usr-abc"}


async def test_extract_ignores_unknown_params() -> None:
    async def sample_func(name: str, count: int) -> None: ...

    sig = inspect.signature(sample_func)
    attrs = _extract_span_attributes(sig, ("hello", 42), {})
    assert attrs == {}


async def test_traced_decorator_preserves_return_value() -> None:
    @traced
    async def add(a: int, b: int) -> int:
        return a + b

    result = await add(2, 3)
    assert result == 5


async def test_traced_decorator_propagates_exceptions() -> None:
    @traced
    async def fail() -> None:
        msg = "boom"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="boom"):
        await fail()


async def test_context_filter_adds_fields_from_context() -> None:
    ctx = RequestContext(user_id="usr-1", org_id="org-2")
    token = request_context.set(ctx)
    try:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        f = RequestContextFilter()
        f.filter(record)
        attrs = vars(record)
        assert attrs["user_id"] == "usr-1"
        assert attrs["org_id"] == "org-2"
    finally:
        request_context.reset(token)


async def test_context_filter_defaults_when_no_context() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="hello",
        args=(),
        exc_info=None,
    )
    f = RequestContextFilter()
    f.filter(record)
    attrs = vars(record)
    assert attrs["user_id"] == ""
    assert attrs["org_id"] == ""


async def test_emit_event_logs_with_extra(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.events"):
        emit_event("order.created", order_id="ord-1", listing_id="lst-2")
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.message == "order.created"
    assert vars(record)["event.name"] == "order.created"
    assert vars(record)["order_id"] == "ord-1"


async def test_trace_id_middleware_sets_header_when_span_valid() -> None:
    test_app = FastAPI()
    test_app.add_middleware(TraceIDMiddleware)

    @test_app.get("/test")
    async def _endpoint() -> dict[str, bool]:
        return {"ok": True}

    mock_span_ctx = MagicMock()
    mock_span_ctx.is_valid = True
    mock_span_ctx.trace_id = 0x0102030405060708090A0B0C0D0E0F10

    mock_span = MagicMock()
    mock_span.get_span_context.return_value = mock_span_ctx

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.observability.middleware.trace.get_current_span", return_value=mock_span):
            resp = await client.get("/test")

    assert resp.status_code == 200
    assert resp.headers["x-trace-id"] == "0102030405060708090a0b0c0d0e0f10"


async def test_trace_id_middleware_no_header_when_span_invalid() -> None:
    test_app = FastAPI()
    test_app.add_middleware(TraceIDMiddleware)

    @test_app.get("/test")
    async def _endpoint() -> dict[str, bool]:
        return {"ok": True}

    mock_span_ctx = MagicMock()
    mock_span_ctx.is_valid = False

    mock_span = MagicMock()
    mock_span.get_span_context.return_value = mock_span_ctx

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.observability.middleware.trace.get_current_span", return_value=mock_span):
            resp = await client.get("/test")

    assert resp.status_code == 200
    assert "x-trace-id" not in resp.headers
