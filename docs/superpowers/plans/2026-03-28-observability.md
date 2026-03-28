# Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add comprehensive observability (traces, logs, metrics) to the rental platform using OpenTelemetry + ClickHouse + Grafana.

**Architecture:** App emits OTLP via OpenTelemetry SDK to an OTel Collector, which exports to ClickHouse. Grafana reads from ClickHouse with pre-provisioned dashboards. Every service function gets a `@traced` decorator and business events are emitted as structured logs with metrics counters. A `TraceIDMiddleware` returns `X-Trace-Id` on every response for frontend correlation.

**Tech Stack:** opentelemetry-api, opentelemetry-sdk, opentelemetry-exporter-otlp-proto-grpc, opentelemetry-instrumentation-fastapi, opentelemetry-instrumentation-asyncpg, ClickHouse, Grafana with grafana-clickhouse-datasource plugin

**Spec:** `docs/superpowers/specs/2026-03-28-observability-design.md`

**Python Conventions (from CLAUDE.md):**
- Python 3.14, strict mypy, no `# type: ignore`, no `from __future__ import annotations`
- Ruff with `select = ["ALL"]`, line length 119
- All functions fully typed, no implicit `Any`
- Async everywhere
- Run `task lint:fix && task typecheck` before committing

---

## File Structure

### New files

```
app/observability/
├── __init__.py          # setup_observability(), shutdown_observability()
├── context.py           # RequestContext dataclass, ContextVar
├── tracing.py           # TracerProvider setup, @traced decorator, _extract_span_attributes
├── logs.py              # LoggerProvider setup, RequestContextFilter
├── metrics.py           # MeterProvider setup, custom meters (counters, histograms)
├── events.py            # emit_event() helper
└── middleware.py         # TraceIDMiddleware (X-Trace-Id header + ContextVar reset)

config/
├── otel-collector.yaml       # OTel Collector config (dev, no TTL)
├── otel-collector-prod.yaml  # OTel Collector config (prod, with TTL)
└── grafana/
    ├── provisioning/
    │   ├── datasources/
    │   │   └── clickhouse.yaml
    │   └── dashboards/
    │       └── default.yaml
    └── dashboards/
        ├── api-overview.json
        ├── traces-explorer.json
        ├── business-events.json
        └── infrastructure.json

tests/test_observability.py   # Tests for decorator, middleware, events, context
```

### Modified files

```
pyproject.toml                  # Add OTel dependencies + mypy overrides
app/core/config.py              # Add ObservabilitySettings + expose_headers in CORSSettings
config/base.yaml                # Add observability section + cors.expose_headers
config/dev.yaml                 # (no changes needed — inherits from base)
config/test.yaml                # Add observability.enabled: false
config/prod.yaml                # Add observability section with prod settings
app/main.py                     # Wire lifespan, add error logging
app/users/service.py            # Add @traced + emit_event + metrics
app/organizations/service.py    # Add @traced + emit_event + metrics
app/listings/service.py         # Add @traced + emit_event
app/orders/service.py           # Add @traced + emit_event + metrics
docker-compose.dev.yml          # Add OTel Collector, ClickHouse, Grafana services
docker-compose.prod.yml         # Add OTel Collector, ClickHouse, Grafana services
Taskfile.yml                    # Add observability-related tasks
```

---

### Task 1: Add Python Dependencies and Configuration Model

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/core/config.py`
- Modify: `config/base.yaml`
- Modify: `config/test.yaml`
- Modify: `config/prod.yaml`

- [ ] **Step 1: Add OTel dependencies to pyproject.toml**

Add to `[tool.poetry.dependencies]`:

```toml
opentelemetry-api = "*"
opentelemetry-sdk = "*"
opentelemetry-exporter-otlp-proto-grpc = "*"
opentelemetry-instrumentation-fastapi = "*"
opentelemetry-instrumentation-asyncpg = "*"
```

Add mypy overrides for OTel and grpc (they lack complete type stubs):

```toml
[[tool.mypy.overrides]]
module = ["opentelemetry.*"]
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = ["grpc.*"]
ignore_missing_imports = true
```

- [ ] **Step 2: Run poetry lock and install**

Run: `poetry lock && poetry install`
Expected: Dependencies resolve and install successfully.

Note: If any package does not support Python 3.14 yet, check for a newer version or use `--no-build-isolation`. OTel packages are pure Python and should work.

- [ ] **Step 3: Add ObservabilitySettings and update CORSSettings in config.py**

In `app/core/config.py`, add `ObservabilitySettings` model and update `CORSSettings` to include `expose_headers`. Add `observability` field to `Settings`:

```python
class ObservabilitySettings(BaseModel):
    enabled: bool = True
    otlp_endpoint: str = "localhost:4317"
    service_name: str = "rental-platform"
    console_log_level: str = "DEBUG"
    otel_log_level: str = "DEBUG"
    metrics_export_interval_seconds: int = 30
```

Add `expose_headers` to `CORSSettings`:

```python
class CORSSettings(BaseModel):
    allow_origins: list[str] = []
    allow_methods: list[str] = ["*"]
    allow_headers: list[str] = ["*"]
    allow_credentials: bool = True
    expose_headers: list[str] = []
```

Add to `Settings`:

```python
class Settings(BaseSettings):
    # ... existing fields ...
    observability: ObservabilitySettings = ObservabilitySettings()
```

Update `create_app()` in `app/main.py` to pass `expose_headers`:

```python
application.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors.allow_origins,
    allow_credentials=settings.cors.allow_credentials,
    allow_methods=settings.cors.allow_methods,
    allow_headers=settings.cors.allow_headers,
    expose_headers=settings.cors.expose_headers,
)
```

- [ ] **Step 4: Update YAML config files**

`config/base.yaml` — append:

```yaml
observability:
  enabled: true
  otlp_endpoint: "localhost:4317"
  service_name: "rental-platform"
  console_log_level: DEBUG
  otel_log_level: DEBUG
  metrics_export_interval_seconds: 30

cors:
  expose_headers:
    - "X-Trace-Id"
```

Note: the `cors` section already exists in base.yaml. Merge `expose_headers` into it (don't duplicate the section).

`config/test.yaml` — append:

```yaml
observability:
  enabled: false
```

`config/prod.yaml` — append:

```yaml
observability:
  enabled: true
  otlp_endpoint: "otel-collector:4317"
  service_name: "rental-platform"
  console_log_level: WARNING
  otel_log_level: DEBUG
  metrics_export_interval_seconds: 60
```

- [ ] **Step 5: Verify config loads correctly**

Run: `APP_ENV=test poetry run python -c "from app.core.config import get_settings; s = get_settings(); print(s.observability.enabled, s.cors.expose_headers)"`
Expected: `False ['X-Trace-Id']`

- [ ] **Step 6: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml poetry.lock app/core/config.py config/base.yaml config/test.yaml config/prod.yaml app/main.py
git commit -m "feat(observability): add OTel dependencies and configuration model"
```

---

### Task 2: Request Context and Tracing Core

**Files:**
- Create: `app/observability/__init__.py` (empty placeholder)
- Create: `app/observability/context.py`
- Create: `app/observability/tracing.py`
- Create: `tests/test_observability.py`

- [ ] **Step 1: Create the observability package with empty __init__.py**

Create `app/observability/__init__.py` with a placeholder docstring (will be filled in Task 6):

```python
"""Observability setup: OpenTelemetry tracing, logging, and metrics."""
```

- [ ] **Step 2: Write the context module**

Create `app/observability/context.py`:

```python
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class RequestContext:
    user_id: str = ""
    org_id: str = ""
    order_id: str = ""
    listing_id: str = ""
    member_id: str = ""


request_context: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)
```

- [ ] **Step 3: Write the failing test for _extract_span_attributes**

Create `tests/test_observability.py`:

```python
import inspect

from app.observability.tracing import _extract_span_attributes


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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `poetry run pytest tests/test_observability.py -v`
Expected: FAIL — `_extract_span_attributes` does not exist yet.

- [ ] **Step 5: Write the tracing module**

Create `app/observability/tracing.py`:

```python
import inspect
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.observability.context import request_context

P = ParamSpec("P")
R = TypeVar("R")

_provider: TracerProvider | None = None

_ID_PARAM_MAP: dict[str, str] = {
    "user_id": "app.user_id",
    "org_id": "app.org_id",
    "organization_id": "app.org_id",
    "order_id": "app.order_id",
    "listing_id": "app.listing_id",
    "member_id": "app.member_id",
}

_MODEL_ATTR_MAP: dict[str, str] = {
    "User": "app.user_id",
    "Organization": "app.org_id",
    "Listing": "app.listing_id",
    "Order": "app.order_id",
}


def _extract_span_attributes(
    sig: inspect.Signature,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, str]:
    attrs: dict[str, str] = {}
    try:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
    except TypeError:
        return attrs

    for name, value in bound.arguments.items():
        if name in _ID_PARAM_MAP and isinstance(value, str):
            attrs[_ID_PARAM_MAP[name]] = value
        elif hasattr(value, "id") and hasattr(value, "__class__"):
            class_name = type(value).__name__
            attr_key = _MODEL_ATTR_MAP.get(class_name)
            if attr_key is not None:
                model_id = getattr(value, "id", None)
                if isinstance(model_id, str):
                    attrs[attr_key] = model_id
    return attrs


def setup_tracing(resource: Resource, endpoint: str) -> None:
    global _provider  # noqa: PLW0603
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    _provider = TracerProvider(resource=resource)
    _provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(_provider)


def shutdown_tracing() -> None:
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()


def traced(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]:
    sig = inspect.signature(func)

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        tracer = trace.get_tracer(func.__module__)
        attrs = _extract_span_attributes(sig, args, kwargs)

        # Enrich request context with extracted attributes
        ctx = request_context.get()
        if ctx is not None:
            for attr_key, attr_val in attrs.items():
                field = attr_key.removeprefix("app.")
                if hasattr(ctx, field):
                    setattr(ctx, field, attr_val)

        with tracer.start_as_current_span(
            f"{func.__module__}.{func.__name__}",
            attributes=attrs,
        ):
            return await func(*args, **kwargs)

    return wrapper
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `poetry run pytest tests/test_observability.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 7: Write test for @traced decorator**

Append to `tests/test_observability.py`:

```python
from app.observability.tracing import traced


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
```

Add `import pytest` at the top of the test file.

- [ ] **Step 8: Run tests**

Run: `poetry run pytest tests/test_observability.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 9: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS. Fix any issues.

- [ ] **Step 10: Commit**

```bash
git add app/observability/__init__.py app/observability/context.py app/observability/tracing.py tests/test_observability.py
git commit -m "feat(observability): add request context and tracing core with @traced decorator"
```

---

### Task 3: Structured Logging

**Files:**
- Create: `app/observability/logs.py`
- Modify: `tests/test_observability.py`

- [ ] **Step 1: Write the failing test for RequestContextFilter**

Append to `tests/test_observability.py`:

```python
import logging

from app.observability.context import RequestContext, request_context
from app.observability.logs import RequestContextFilter


async def test_context_filter_adds_fields_from_context() -> None:
    ctx = RequestContext(user_id="usr-1", org_id="org-2")
    token = request_context.set(ctx)
    try:
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0, msg="hello", args=(), exc_info=None,
        )
        f = RequestContextFilter()
        f.filter(record)
        assert getattr(record, "user_id") == "usr-1"
        assert getattr(record, "org_id") == "org-2"
    finally:
        request_context.reset(token)


async def test_context_filter_defaults_when_no_context() -> None:
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0, msg="hello", args=(), exc_info=None,
    )
    f = RequestContextFilter()
    f.filter(record)
    assert getattr(record, "user_id") == ""
    assert getattr(record, "org_id") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_observability.py::test_context_filter_adds_fields_from_context -v`
Expected: FAIL — `RequestContextFilter` does not exist.

- [ ] **Step 3: Write the logging module**

Create `app/observability/logs.py`:

```python
import logging

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from app.observability.context import request_context

_provider: LoggerProvider | None = None


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = request_context.get()
        if ctx is not None:
            setattr(record, "user_id", ctx.user_id)
            setattr(record, "org_id", ctx.org_id)
            setattr(record, "order_id", ctx.order_id)
            setattr(record, "listing_id", ctx.listing_id)
        else:
            setattr(record, "user_id", "")
            setattr(record, "org_id", "")
            setattr(record, "order_id", "")
            setattr(record, "listing_id", "")
        return True


def setup_logging(resource: Resource, endpoint: str, console_level: str, otel_level: str) -> None:
    global _provider  # noqa: PLW0603

    exporter = OTLPLogExporter(endpoint=endpoint, insecure=True)
    _provider = LoggerProvider(resource=resource)
    _provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(_provider)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console handler — human-readable
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, console_level.upper()))
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S"),
    )

    # OTel handler — sends to Collector
    otel_handler = LoggingHandler(level=getattr(logging, otel_level.upper()), logger_provider=_provider)

    # Attach context filter to both handlers
    ctx_filter = RequestContextFilter()
    console_handler.addFilter(ctx_filter)
    otel_handler.addFilter(ctx_filter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(otel_handler)


def shutdown_logging() -> None:
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()
```

Note: The imports use `_logs` paths. If your opentelemetry-sdk version has stabilized the logs API, the imports may be `opentelemetry.logs`, `opentelemetry.sdk.logs`, etc. Adjust if needed.

- [ ] **Step 4: Run tests**

Run: `poetry run pytest tests/test_observability.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/observability/logs.py tests/test_observability.py
git commit -m "feat(observability): add structured logging with OTel bridge and context filter"
```

---

### Task 4: Metrics and Business Events

**Files:**
- Create: `app/observability/metrics.py`
- Create: `app/observability/events.py`
- Modify: `tests/test_observability.py`

- [ ] **Step 1: Write the failing test for emit_event**

Append to `tests/test_observability.py`:

```python
from app.observability.events import emit_event


async def test_emit_event_logs_with_extra(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.events"):
        emit_event("order.created", order_id="ord-1", listing_id="lst-2")

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.message == "order.created"
    assert getattr(record, "event.name") == "order.created"
    assert getattr(record, "order_id") == "ord-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_observability.py::test_emit_event_logs_with_extra -v`
Expected: FAIL — `emit_event` does not exist.

- [ ] **Step 3: Write the metrics module**

Create `app/observability/metrics.py`:

```python
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

_provider: MeterProvider | None = None

_meter = metrics.get_meter("rental-platform")

# ── Counters ──
orders_created = _meter.create_counter("app.orders.created", description="Number of orders created")
order_transitions = _meter.create_counter("app.orders.transitions", description="Order status transitions")
auth_attempts = _meter.create_counter("app.auth.attempts", description="Authentication attempts")
dadata_requests = _meter.create_counter("app.dadata.requests", description="Dadata API requests")
business_events_counter = _meter.create_counter("app.business_events", description="Business events emitted")

# ── Histograms ──
dadata_duration = _meter.create_histogram(
    "app.dadata.duration", description="Dadata API call duration", unit="ms",
)


def setup_metrics(resource: Resource, endpoint: str, export_interval_ms: int) -> None:
    global _provider  # noqa: PLW0603
    exporter = OTLPMetricExporter(endpoint=endpoint, insecure=True)
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=export_interval_ms)
    _provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(_provider)


def shutdown_metrics() -> None:
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()
```

- [ ] **Step 4: Write the events module**

Create `app/observability/events.py`:

```python
import logging
from typing import Any

from app.observability.metrics import business_events_counter

logger = logging.getLogger("app.events")


def emit_event(event: str, **attributes: Any) -> None:
    extra: dict[str, Any] = {"event.name": event, **attributes}
    logger.info(event, extra=extra)
    business_events_counter.add(1, {"event_name": event})
```

- [ ] **Step 5: Run tests**

Run: `poetry run pytest tests/test_observability.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 6: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/observability/metrics.py app/observability/events.py tests/test_observability.py
git commit -m "feat(observability): add metrics collection and business event emitter"
```

---

### Task 5: TraceID Middleware

**Files:**
- Create: `app/observability/middleware.py`
- Modify: `tests/test_observability.py`

- [ ] **Step 1: Write the failing test for TraceIDMiddleware**

Append to `tests/test_observability.py`:

```python
from unittest.mock import MagicMock, patch

import httpx
from fastapi import FastAPI
from httpx import ASGITransport

from app.observability.middleware import TraceIDMiddleware


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_observability.py::test_trace_id_middleware_sets_header_when_span_valid -v`
Expected: FAIL — `TraceIDMiddleware` does not exist.

- [ ] **Step 3: Write the middleware module**

Create `app/observability/middleware.py`:

```python
from collections.abc import Awaitable, Callable

from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.observability.context import RequestContext, request_context


class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        ctx = RequestContext()
        token = request_context.set(ctx)
        try:
            response = await call_next(request)
            span = trace.get_current_span()
            span_context = span.get_span_context()
            if span_context.is_valid:
                trace_id = format(span_context.trace_id, "032x")
                response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            request_context.reset(token)
```

- [ ] **Step 4: Run tests**

Run: `poetry run pytest tests/test_observability.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 5: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/observability/middleware.py tests/test_observability.py
git commit -m "feat(observability): add TraceID middleware with X-Trace-Id response header"
```

---

### Task 6: Setup Orchestration and main.py Integration

**Files:**
- Modify: `app/observability/__init__.py`
- Modify: `app/main.py`

- [ ] **Step 1: Write the orchestration module**

Replace `app/observability/__init__.py` content:

```python
from fastapi import FastAPI
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource

from app.core.config import get_settings
from app.observability.logs import setup_logging, shutdown_logging
from app.observability.metrics import setup_metrics, shutdown_metrics
from app.observability.middleware import TraceIDMiddleware
from app.observability.tracing import setup_tracing, shutdown_tracing


def setup_observability(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.observability.enabled:
        return

    resource = Resource.create({
        "service.name": settings.observability.service_name,
        "deployment.environment": settings.app_env,
    })
    endpoint = settings.observability.otlp_endpoint
    obs = settings.observability

    setup_tracing(resource, endpoint)
    setup_metrics(resource, endpoint, obs.metrics_export_interval_seconds * 1000)
    setup_logging(resource, endpoint, obs.console_log_level, obs.otel_log_level)

    FastAPIInstrumentor.instrument_app(app)
    AsyncPGInstrumentor().instrument()

    app.add_middleware(TraceIDMiddleware)


def shutdown_observability() -> None:
    settings = get_settings()
    if not settings.observability.enabled:
        return
    shutdown_tracing()
    shutdown_metrics()
    shutdown_logging()
```

- [ ] **Step 2: Update main.py lifespan and error handler**

Update `app/main.py`. The lifespan should call `setup_observability` before DB init and `shutdown_observability` after:

```python
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from tortoise.contrib.fastapi import RegisterTortoise

from app.core.config import get_settings
from app.core.database import get_tortoise_config
from app.core.exceptions import AppError, app_error_handler
from app.listings.models import ListingCategory
from app.listings.router import router as listings_router
from app.observability import setup_observability, shutdown_observability
from app.orders.router import router as orders_router
from app.organizations.router import router as organizations_router
from app.users.router import router as users_router

logger = logging.getLogger(__name__)


async def _seed_categories() -> None:
    if await ListingCategory.exists():
        return
    settings = get_settings()
    for name in settings.seed_categories:
        await ListingCategory.create(name=name, verified=True)
    logger.info("Seeded %d listing categories", len(settings.seed_categories))


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    setup_observability(application)
    config = get_tortoise_config()
    async with RegisterTortoise(
        application,
        config=config,
        generate_schemas=True,
    ):
        await _seed_categories()
        yield
    shutdown_observability()


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, AppError):
        return await app_error_handler(request, exc)
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def create_app() -> FastAPI:
    application = FastAPI(title="Rental Platform", lifespan=lifespan)

    settings = get_settings()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.allow_origins,
        allow_credentials=settings.cors.allow_credentials,
        allow_methods=settings.cors.allow_methods,
        allow_headers=settings.cors.allow_headers,
        expose_headers=settings.cors.expose_headers,
    )

    application.add_exception_handler(AppError, _handle_app_error)
    application.include_router(users_router)
    application.include_router(organizations_router)
    application.include_router(listings_router)
    application.include_router(orders_router)

    return application


app = create_app()
```

- [ ] **Step 3: Run all existing tests to verify no regressions**

Run: `task test`
Expected: All existing tests PASS. Observability is disabled in test config so setup_observability is a no-op.

- [ ] **Step 4: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/observability/__init__.py app/main.py
git commit -m "feat(observability): wire setup/shutdown into app lifespan"
```

---

### Task 7: Instrument Users and Organizations Services

**Files:**
- Modify: `app/users/service.py`
- Modify: `app/organizations/service.py`

- [ ] **Step 1: Instrument users/service.py**

Add imports at the top of `app/users/service.py`:

```python
from app.observability.events import emit_event
from app.observability.metrics import auth_attempts
from app.observability.tracing import traced
```

Add `@traced` to every public function: `register`, `authenticate`, `get_by_id`, `update_me`, `change_user_role`, `change_privilege`.

Add business events and metrics to key functions:

In `register()`, after creating the user and token:
```python
    emit_event("user.registered", user_id=user.id)
```

In `authenticate()`, after successful auth:
```python
    auth_attempts.add(1, {"result": "success"})
    emit_event("user.authenticated", user_id=user.id)
```

In `authenticate()`, in the failure branches — before each `raise InvalidCredentialsError`, emit both metric and event:
```python
    auth_attempts.add(1, {"result": "failed"})
    emit_event("user.auth_failed")
```

Before `raise AccountSuspendedError`:
```python
    auth_attempts.add(1, {"result": "suspended"})
```

Complete `authenticate` after changes:
```python
@traced
async def authenticate(email: str, password: str) -> TokenResponse:
    user = await User.get_or_none(email=email)
    if user is None:
        auth_attempts.add(1, {"result": "failed"})
        emit_event("user.auth_failed")
        raise InvalidCredentialsError("Incorrect username or password")
    if not verify_password(password, user.hashed_password):
        auth_attempts.add(1, {"result": "failed"})
        emit_event("user.auth_failed")
        raise InvalidCredentialsError("Incorrect username or password")
    if user.role == UserRole.SUSPENDED:
        auth_attempts.add(1, {"result": "suspended"})
        raise AccountSuspendedError("Account suspended")
    token = create_access_token(user.id)
    auth_attempts.add(1, {"result": "success"})
    emit_event("user.authenticated", user_id=user.id)
    return TokenResponse(access_token=token)
```

- [ ] **Step 2: Instrument organizations/service.py**

Add imports at the top of `app/organizations/service.py`:

```python
import time

from app.observability.events import emit_event
from app.observability.metrics import dadata_duration, dadata_requests
from app.observability.tracing import traced
```

Add `@traced` to every public function: `create_organization`, `get_organization`, `list_user_organizations`, `replace_contacts`, `get_payment_details`, `upsert_payment_details`, `invite_member`, `join_organization`, `approve_candidate`, `accept_invitation`, `change_member_role`, `remove_member`, `list_members`, `verify_organization`.

Do NOT add `@traced` to private functions (`_extract_dadata_fields`, `_is_last_admin`).

In `create_organization()`, wrap the Dadata call with timing and events:

```python
    start = time.monotonic()
    try:
        results = await asyncio.to_thread(dadata.find_by_id, "party", data.inn)
        duration_ms = (time.monotonic() - start) * 1000
        dadata_requests.add(1, {"success": "true"})
        dadata_duration.record(duration_ms)
        emit_event("dadata.called", inn=data.inn, success="true", duration_ms=str(int(duration_ms)))
    except Exception as e:
        duration_ms = (time.monotonic() - start) * 1000
        dadata_requests.add(1, {"success": "false"})
        dadata_duration.record(duration_ms)
        emit_event("dadata.called", inn=data.inn, success="false", duration_ms=str(int(duration_ms)))
        raise ExternalServiceError("Dadata service unavailable") from e
```

At the end of `create_organization()` (before return):
```python
    emit_event("organization.created", org_id=org.id, inn=data.inn)
```

In `verify_organization()` (before return):
```python
    emit_event("organization.verified", org_id=org_id)
```

In `invite_member()` (before return):
```python
    emit_event("membership.invited", org_id=org_id, user_id=data.user_id, role=data.role.value)
```

In `accept_invitation()` (before return):
```python
    emit_event("membership.accepted", org_id=org_id, user_id=user.id)
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `poetry run pytest tests/test_users.py tests/test_organizations.py -v`
Expected: All tests PASS. The `@traced` decorator is a no-op without OTel initialized, and `emit_event` just logs.

- [ ] **Step 4: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/users/service.py app/organizations/service.py
git commit -m "feat(observability): instrument users and organizations services"
```

---

### Task 8: Instrument Listings and Orders Services

**Files:**
- Modify: `app/listings/service.py`
- Modify: `app/orders/service.py`

- [ ] **Step 1: Instrument listings/service.py**

Add imports at the top of `app/listings/service.py`:

```python
from app.observability.events import emit_event
from app.observability.tracing import traced
```

Add `@traced` to every public function: `create_category`, `list_public_categories`, `create_listing`, `update_listing`, `delete_listing`, `change_listing_status`, `list_org_listings`, `list_public_listings`, `list_org_categories`.

Do NOT add `@traced` to private functions (`_verified_org_ids`, `_category_to_read`, `_validate_category`).

In `create_listing()` (before return):
```python
    emit_event("listing.created", listing_id=listing.id, org_id=org.id)
```

In `change_listing_status()` — capture old status before the change, emit event before return:
```python
@traced
async def change_listing_status(listing: Listing, status: ListingStatus) -> ListingRead:
    old_status = listing.status
    listing.status = status
    await listing.save()
    await listing.fetch_related("category")
    emit_event("listing.status_changed", listing_id=listing.id, old_status=old_status.value, new_status=status.value)
    return ListingRead.model_validate(listing)
```

- [ ] **Step 2: Instrument orders/service.py**

Add imports at the top of `app/orders/service.py`:

```python
from app.observability.events import emit_event
from app.observability.metrics import order_transitions, orders_created
from app.observability.tracing import traced
```

Add `@traced` to every public function: `create_order`, `offer_order`, `reject_order`, `confirm_order`, `decline_order`, `cancel_order_by_user`, `cancel_order_by_org`, `get_order`, `list_user_orders`, `list_org_orders`.

Do NOT add `@traced` to private functions (`_apply_auto_transition`, `_to_read`, `_cancel_order`).

In `create_order()` (before return):
```python
    orders_created.add(1, {"org_id": listing.organization.id, "listing_id": data.listing_id})
    emit_event("order.created", order_id=order.id, listing_id=data.listing_id, user_id=user.id)
```

For every function that changes order status, emit event and record metric. Create a helper at the module level (after imports):

```python
def _record_transition(order_id: str, old_status: OrderStatus, new_status: OrderStatus) -> None:
    order_transitions.add(1, {"from_status": old_status.value, "to_status": new_status.value})
    emit_event("order.status_changed", order_id=order_id, old_status=old_status.value, new_status=new_status.value)
```

Use it in `offer_order`, `reject_order`, `confirm_order`, `decline_order`. Example for `offer_order`:

```python
@traced
async def offer_order(order: Order, data: OrderOffer) -> OrderRead:
    old_status = order.status
    new_status = transition(order.status, OrderAction.OFFER_BY_ORG)
    order.status = new_status
    order.offered_cost = data.offered_cost
    order.offered_start_date = data.offered_start_date
    order.offered_end_date = data.offered_end_date
    await order.save()
    _record_transition(order.id, old_status, new_status)
    return await _to_read(order)
```

Apply the same pattern to `reject_order`, `confirm_order`, `decline_order`.

For `_cancel_order` (private, shared by user/org cancel): add event emission inside it since both public cancel functions delegate to it:

```python
async def _cancel_order(order: Order, action: OrderAction) -> OrderRead:
    old_status = order.status
    order.status = transition(order.status, action)
    await order.save()

    await order.fetch_related("listing")
    listing: Listing = order.listing
    if listing.status == ListingStatus.IN_RENT:
        listing.status = ListingStatus.PUBLISHED
        await listing.save()

    _record_transition(order.id, old_status, order.status)
    return OrderRead.model_validate(order)
```

- [ ] **Step 3: Run existing tests**

Run: `poetry run pytest tests/test_listings.py tests/test_orders.py tests/test_order_state_machine.py -v`
Expected: All tests PASS.

- [ ] **Step 4: Run full test suite**

Run: `task test`
Expected: All tests PASS.

- [ ] **Step 5: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/listings/service.py app/orders/service.py
git commit -m "feat(observability): instrument listings and orders services"
```

---

### Task 9: Dev Infrastructure

**Files:**
- Modify: `docker-compose.dev.yml`
- Create: `config/otel-collector.yaml`
- Create: `config/grafana/provisioning/datasources/clickhouse.yaml`
- Create: `config/grafana/provisioning/dashboards/default.yaml`
- Modify: `Taskfile.yml`

- [ ] **Step 1: Create OTel Collector config**

Create `config/otel-collector.yaml`:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 1000

exporters:
  clickhouse:
    endpoint: tcp://clickhouse:9000
    database: otel
    create_schema: true
    logs_table_name: otel_logs
    traces_table_name: otel_traces
    metrics_table_name: otel_metrics

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [clickhouse]
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [clickhouse]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [clickhouse]
```

- [ ] **Step 2: Create Grafana provisioning configs**

Create directory structure first:
```bash
mkdir -p config/grafana/provisioning/datasources config/grafana/provisioning/dashboards config/grafana/dashboards
```

Create `config/grafana/provisioning/datasources/clickhouse.yaml`:

```yaml
apiVersion: 1

datasources:
  - name: ClickHouse
    type: grafana-clickhouse-datasource
    uid: clickhouse
    access: proxy
    jsonData:
      host: clickhouse
      port: 9000
      protocol: native
      defaultDatabase: otel
    isDefault: true
    editable: true
```

Create `config/grafana/provisioning/dashboards/default.yaml`:

```yaml
apiVersion: 1

providers:
  - name: default
    orgId: 1
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

- [ ] **Step 3: Update docker-compose.dev.yml**

Replace `docker-compose.dev.yml` with:

```yaml
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_USER: rental
      POSTGRES_PASSWORD: rental
      POSTGRES_DB: rental_dev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  clickhouse:
    image: clickhouse/clickhouse-server
    volumes:
      - clickhouse_data:/var/lib/clickhouse

  otel-collector:
    image: otel/opentelemetry-collector-contrib
    command: ["--config=/etc/otelcol-contrib/config.yaml"]
    volumes:
      - ./config/otel-collector.yaml:/etc/otelcol-contrib/config.yaml:ro
    ports:
      - "4317:4317"
    depends_on:
      - clickhouse

  grafana:
    image: grafana/grafana
    environment:
      GF_INSTALL_PLUGINS: grafana-clickhouse-datasource
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Admin
    volumes:
      - ./config/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./config/grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports:
      - "3001:3000"
    depends_on:
      - clickhouse

volumes:
  pgdata:
  clickhouse_data:
```

- [ ] **Step 4: Update Taskfile.yml**

Add new infra desc to reflect the new services. Update the `infra:up` desc:

```yaml
  infra:up:
    desc: Start dev infrastructure (DB, OTel Collector, ClickHouse, Grafana)
    cmds:
      - docker compose -p rental-dev -f docker-compose.dev.yml up -d
```

- [ ] **Step 5: Test infrastructure starts**

Run: `task infra:down && task infra:up`
Expected: All 4 services start. Verify:
```bash
docker compose -p rental-dev -f docker-compose.dev.yml ps
```
Should show: db, clickhouse, otel-collector, grafana all running.

- [ ] **Step 6: Verify Grafana is accessible**

Open `http://localhost:3001` in a browser. Should show Grafana with the ClickHouse datasource pre-configured (check Settings → Data Sources).

- [ ] **Step 7: Commit**

```bash
git add docker-compose.dev.yml config/otel-collector.yaml config/grafana/
git commit -m "feat(observability): add dev infrastructure (OTel Collector, ClickHouse, Grafana)"
```

---

### Task 10: Prod Infrastructure

**Files:**
- Create: `config/otel-collector-prod.yaml`
- Modify: `docker-compose.prod.yml`

- [ ] **Step 1: Create prod Collector config**

Create `config/otel-collector-prod.yaml`:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 1000

exporters:
  clickhouse:
    endpoint: tcp://clickhouse:9000
    database: otel
    create_schema: true
    ttl_days: 30
    logs_table_name: otel_logs
    traces_table_name: otel_traces
    metrics_table_name: otel_metrics

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [clickhouse]
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [clickhouse]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [clickhouse]
```

The only difference from dev: `ttl_days: 30` on the clickhouse exporter.

- [ ] **Step 2: Update docker-compose.prod.yml**

Replace `docker-compose.prod.yml` with:

```yaml
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data

  clickhouse:
    image: clickhouse/clickhouse-server
    mem_limit: 2g
    volumes:
      - clickhouse_data:/var/lib/clickhouse

  otel-collector:
    image: otel/opentelemetry-collector-contrib
    command: ["--config=/etc/otelcol-contrib/config.yaml"]
    volumes:
      - ./config/otel-collector-prod.yaml:/etc/otelcol-contrib/config.yaml:ro
    depends_on:
      - clickhouse

  grafana:
    image: grafana/grafana
    environment:
      GF_INSTALL_PLUGINS: grafana-clickhouse-datasource
      GF_AUTH_ANONYMOUS_ENABLED: "false"
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
    volumes:
      - ./config/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./config/grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports:
      - "3001:3000"
    depends_on:
      - clickhouse

  app:
    image: rental-platform:${APP_VERSION:-latest}
    environment:
      APP_ENV: prod
      DATABASE_PASSWORD: ${POSTGRES_PASSWORD}
      JWT_SECRET: ${JWT_SECRET}
      DADATA_API_KEY: ${DADATA_API_KEY:-}
      OBSERVABILITY__OTLP_ENDPOINT: otel-collector:4317
    ports:
      - "8000:8000"
    depends_on:
      - db
      - otel-collector
    command: gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

volumes:
  pgdata:
  clickhouse_data:
```

Key changes from original:
- Added `clickhouse`, `otel-collector`, `grafana` services
- Added `OBSERVABILITY__OTLP_ENDPOINT` env var to app (overrides YAML config via pydantic-settings env nested delimiter)
- app `depends_on` now includes `otel-collector`
- Grafana has auth enabled with admin credentials from env vars
- ClickHouse has 2GB memory limit

- [ ] **Step 3: Commit**

```bash
git add config/otel-collector-prod.yaml docker-compose.prod.yml config/prod.yaml
git commit -m "feat(observability): add prod infrastructure with TTL and auth"
```

---

### Task 11: Grafana Dashboards

**Files:**
- Create: `config/grafana/dashboards/api-overview.json`
- Create: `config/grafana/dashboards/traces-explorer.json`
- Create: `config/grafana/dashboards/business-events.json`
- Create: `config/grafana/dashboards/infrastructure.json`

All dashboards use the ClickHouse datasource `uid: "clickhouse"` and query the `otel` database. The clickhouse-exporter auto-creates tables `otel_traces`, `otel_logs`, `otel_metrics`.

Note: The exact column names and query syntax depend on the clickhouse-exporter version. The queries below use the standard schema. If columns differ at runtime, adjust the SQL.

- [ ] **Step 1: Create API Overview dashboard**

Create `config/grafana/dashboards/api-overview.json`:

```json
{
  "title": "API Overview",
  "uid": "api-overview",
  "tags": ["rental-platform"],
  "time": {"from": "now-1h", "to": "now"},
  "refresh": "30s",
  "schemaVersion": 39,
  "panels": [
    {
      "type": "timeseries",
      "title": "Request Rate by Endpoint",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT toStartOfMinute(Timestamp) AS time, SpanAttributes['http.route'] AS route, count() AS requests FROM otel.otel_traces WHERE SpanKind = 'SPAN_KIND_SERVER' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY time, route ORDER BY time",
          "refId": "A",
          "format": 1
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Latency p50 / p95 / p99",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT toStartOfMinute(Timestamp) AS time, quantile(0.50)(Duration / 1000000) AS p50_ms, quantile(0.95)(Duration / 1000000) AS p95_ms, quantile(0.99)(Duration / 1000000) AS p99_ms FROM otel.otel_traces WHERE SpanKind = 'SPAN_KIND_SERVER' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY time ORDER BY time",
          "refId": "A",
          "format": 1
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Error Rate by Status Code",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT toStartOfMinute(Timestamp) AS time, SpanAttributes['http.response.status_code'] AS status, count() AS cnt FROM otel.otel_traces WHERE SpanKind = 'SPAN_KIND_SERVER' AND toInt32OrZero(SpanAttributes['http.response.status_code']) >= 400 AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY time, status ORDER BY time",
          "refId": "A",
          "format": 1
        }
      ]
    },
    {
      "type": "stat",
      "title": "Active Requests (Last Minute)",
      "gridPos": {"h": 4, "w": 6, "x": 12, "y": 8},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT count() AS active FROM otel.otel_traces WHERE SpanKind = 'SPAN_KIND_SERVER' AND Timestamp >= now() - INTERVAL 1 MINUTE AND Duration = 0",
          "refId": "A",
          "format": 1
        }
      ]
    },
    {
      "type": "table",
      "title": "Top 10 Slowest Endpoints (Last Hour)",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 12},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT SpanAttributes['http.route'] AS route, SpanAttributes['http.request.method'] AS method, quantile(0.95)(Duration / 1000000) AS p95_ms, count() AS requests FROM otel.otel_traces WHERE SpanKind = 'SPAN_KIND_SERVER' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY route, method ORDER BY p95_ms DESC LIMIT 10",
          "refId": "A",
          "format": 2
        }
      ]
    }
  ]
}
```

- [ ] **Step 2: Create Traces Explorer dashboard**

Create `config/grafana/dashboards/traces-explorer.json`:

```json
{
  "title": "Traces Explorer",
  "uid": "traces-explorer",
  "tags": ["rental-platform"],
  "time": {"from": "now-1h", "to": "now"},
  "refresh": "30s",
  "schemaVersion": 39,
  "templating": {
    "list": [
      {
        "name": "trace_id",
        "type": "textbox",
        "label": "Trace ID",
        "current": {"value": ""}
      },
      {
        "name": "user_id",
        "type": "textbox",
        "label": "User ID",
        "current": {"value": ""}
      },
      {
        "name": "org_id",
        "type": "textbox",
        "label": "Organization ID",
        "current": {"value": ""}
      },
      {
        "name": "order_id",
        "type": "textbox",
        "label": "Order ID",
        "current": {"value": ""}
      }
    ]
  },
  "panels": [
    {
      "type": "table",
      "title": "Recent Traces",
      "gridPos": {"h": 12, "w": 24, "x": 0, "y": 0},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT TraceId, SpanAttributes['http.route'] AS route, SpanAttributes['http.request.method'] AS method, SpanAttributes['http.response.status_code'] AS status, Duration / 1000000 AS duration_ms, Timestamp FROM otel.otel_traces WHERE SpanKind = 'SPAN_KIND_SERVER' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime AND (length('${trace_id}') = 0 OR TraceId = '${trace_id}') AND (length('${user_id}') = 0 OR SpanAttributes['app.user_id'] = '${user_id}') AND (length('${org_id}') = 0 OR SpanAttributes['app.org_id'] = '${org_id}') AND (length('${order_id}') = 0 OR SpanAttributes['app.order_id'] = '${order_id}') ORDER BY Timestamp DESC LIMIT 100",
          "refId": "A",
          "format": 2
        }
      ]
    },
    {
      "type": "table",
      "title": "Trace Spans (select a Trace ID above)",
      "gridPos": {"h": 12, "w": 24, "x": 0, "y": 12},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT SpanName, SpanKind, Duration / 1000000 AS duration_ms, StatusCode, SpanAttributes, Timestamp FROM otel.otel_traces WHERE TraceId = '${trace_id}' ORDER BY Timestamp ASC",
          "refId": "A",
          "format": 2
        }
      ]
    },
    {
      "type": "table",
      "title": "Error Traces",
      "gridPos": {"h": 10, "w": 24, "x": 0, "y": 24},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT TraceId, SpanAttributes['http.route'] AS route, SpanAttributes['http.response.status_code'] AS status, StatusMessage, Duration / 1000000 AS duration_ms, Timestamp FROM otel.otel_traces WHERE SpanKind = 'SPAN_KIND_SERVER' AND StatusCode = 'STATUS_CODE_ERROR' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime ORDER BY Timestamp DESC LIMIT 50",
          "refId": "A",
          "format": 2
        }
      ]
    }
  ]
}
```

- [ ] **Step 3: Create Business Events dashboard**

Create `config/grafana/dashboards/business-events.json`:

```json
{
  "title": "Business Events",
  "uid": "business-events",
  "tags": ["rental-platform"],
  "time": {"from": "now-6h", "to": "now"},
  "refresh": "1m",
  "schemaVersion": 39,
  "panels": [
    {
      "type": "timeseries",
      "title": "Order Creation Rate",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT toStartOfFiveMinutes(Timestamp) AS time, count() AS orders FROM otel.otel_logs WHERE LogAttributes['event.name'] = 'order.created' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY time ORDER BY time",
          "refId": "A",
          "format": 1
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Order Status Transitions",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT toStartOfFiveMinutes(Timestamp) AS time, LogAttributes['new_status'] AS new_status, count() AS transitions FROM otel.otel_logs WHERE LogAttributes['event.name'] = 'order.status_changed' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY time, new_status ORDER BY time",
          "refId": "A",
          "format": 1
        }
      ]
    },
    {
      "type": "piechart",
      "title": "Auth Success / Failure Ratio",
      "gridPos": {"h": 8, "w": 8, "x": 0, "y": 8},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT CASE WHEN LogAttributes['event.name'] = 'user.authenticated' THEN 'success' WHEN LogAttributes['event.name'] = 'user.auth_failed' THEN 'failed' ELSE 'other' END AS result, count() AS cnt FROM otel.otel_logs WHERE LogAttributes['event.name'] IN ('user.authenticated', 'user.auth_failed') AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY result",
          "refId": "A",
          "format": 2
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Organization Registrations",
      "gridPos": {"h": 8, "w": 8, "x": 8, "y": 8},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT toStartOfFiveMinutes(Timestamp) AS time, count() AS registrations FROM otel.otel_logs WHERE LogAttributes['event.name'] = 'organization.created' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY time ORDER BY time",
          "refId": "A",
          "format": 1
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Dadata Call Success Rate & Latency",
      "gridPos": {"h": 8, "w": 8, "x": 16, "y": 8},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT toStartOfFiveMinutes(Timestamp) AS time, LogAttributes['success'] AS success, count() AS calls, avg(toFloat64OrZero(LogAttributes['duration_ms'])) AS avg_ms FROM otel.otel_logs WHERE LogAttributes['event.name'] = 'dadata.called' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY time, success ORDER BY time",
          "refId": "A",
          "format": 1
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Event Rate by Type",
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 16},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT toStartOfFiveMinutes(Timestamp) AS time, LogAttributes['event.name'] AS event, count() AS cnt FROM otel.otel_logs WHERE LogAttributes['event.name'] != '' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY time, event ORDER BY time",
          "refId": "A",
          "format": 1
        }
      ]
    }
  ]
}
```

- [ ] **Step 4: Create Infrastructure dashboard**

Create `config/grafana/dashboards/infrastructure.json`:

```json
{
  "title": "Infrastructure",
  "uid": "infrastructure",
  "tags": ["rental-platform"],
  "time": {"from": "now-1h", "to": "now"},
  "refresh": "30s",
  "schemaVersion": 39,
  "panels": [
    {
      "type": "timeseries",
      "title": "Log Volume by Level",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT toStartOfMinute(Timestamp) AS time, SeverityText AS level, count() AS logs FROM otel.otel_logs WHERE ServiceName = 'rental-platform' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY time, level ORDER BY time",
          "refId": "A",
          "format": 1
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "DB Query Duration (asyncpg)",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT toStartOfMinute(Timestamp) AS time, quantile(0.50)(Duration / 1000000) AS p50_ms, quantile(0.95)(Duration / 1000000) AS p95_ms FROM otel.otel_traces WHERE SpanName LIKE '%asyncpg%' OR SpanAttributes['db.system'] = 'postgresql' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime GROUP BY time ORDER BY time",
          "refId": "A",
          "format": 1
        }
      ]
    },
    {
      "type": "table",
      "title": "Recent Errors (ERROR + WARNING)",
      "gridPos": {"h": 10, "w": 24, "x": 0, "y": 8},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT Timestamp, SeverityText, Body, TraceId, LogAttributes FROM otel.otel_logs WHERE ServiceName = 'rental-platform' AND SeverityNumber >= 13 AND Timestamp >= $__fromTime AND Timestamp <= $__toTime ORDER BY Timestamp DESC LIMIT 100",
          "refId": "A",
          "format": 2
        }
      ]
    },
    {
      "type": "stat",
      "title": "Total Traces (Last Hour)",
      "gridPos": {"h": 4, "w": 6, "x": 0, "y": 18},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT count() AS total FROM otel.otel_traces WHERE SpanKind = 'SPAN_KIND_SERVER' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime",
          "refId": "A",
          "format": 2
        }
      ]
    },
    {
      "type": "stat",
      "title": "Total Logs (Last Hour)",
      "gridPos": {"h": 4, "w": 6, "x": 6, "y": 18},
      "datasource": {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"},
      "targets": [
        {
          "rawSql": "SELECT count() AS total FROM otel.otel_logs WHERE ServiceName = 'rental-platform' AND Timestamp >= $__fromTime AND Timestamp <= $__toTime",
          "refId": "A",
          "format": 2
        }
      ]
    }
  ]
}
```

- [ ] **Step 5: Restart dev infrastructure to pick up dashboards**

Run: `task infra:down && task infra:up`
Expected: All services start. Grafana at `http://localhost:3001` shows 4 dashboards.

- [ ] **Step 6: Commit**

```bash
git add config/grafana/dashboards/
git commit -m "feat(observability): add pre-built Grafana dashboards"
```

---

### Task 12: End-to-End Smoke Test

**Files:** None (manual verification)

- [ ] **Step 1: Ensure dev infrastructure is running**

Run: `docker compose -p rental-dev -f docker-compose.dev.yml ps`
Expected: db, clickhouse, otel-collector, grafana all running.

- [ ] **Step 2: Start the dev server**

Run: `task run` (in a separate terminal or background)
Expected: Uvicorn starts on :8000.

- [ ] **Step 3: Make a few API requests to generate telemetry**

```bash
# Register a user
curl -s -X POST http://localhost:8000/users/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@test.com","password":"StrongPass1","phone":"+79001234567","name":"Test","surname":"User"}' | python -m json.tool

# Login
curl -s -X POST http://localhost:8000/users/token \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@test.com","password":"StrongPass1"}' | python -m json.tool

# Failed login (generates warning + metric)
curl -s -X POST http://localhost:8000/users/token \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@test.com","password":"WrongPass"}' | python -m json.tool
```

- [ ] **Step 4: Verify X-Trace-Id header**

```bash
curl -v -X POST http://localhost:8000/users/token \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@test.com","password":"StrongPass1"}' 2>&1 | grep -i x-trace-id
```

Expected: Response contains `X-Trace-Id: <32-hex-characters>`.

- [ ] **Step 5: Verify data in ClickHouse**

```bash
docker exec -it $(docker ps -qf "name=clickhouse") clickhouse-client \
  --query "SELECT count() FROM otel.otel_traces"

docker exec -it $(docker ps -qf "name=clickhouse") clickhouse-client \
  --query "SELECT count() FROM otel.otel_logs"
```

Expected: Non-zero counts for both traces and logs.

- [ ] **Step 6: Verify Grafana dashboards**

Open `http://localhost:3001`:
1. **API Overview** — should show request rate, latency, and the recent requests
2. **Traces Explorer** — search by trace ID from Step 4, should show spans
3. **Business Events** — should show auth events
4. **Infrastructure** — should show log volume

- [ ] **Step 7: Run the full CI check**

Run: `task ci`
Expected: lint + typecheck + test all PASS.

- [ ] **Step 8: Final commit (if any lint fixes needed)**

```bash
git add -A
git commit -m "chore(observability): final lint fixes"
```
