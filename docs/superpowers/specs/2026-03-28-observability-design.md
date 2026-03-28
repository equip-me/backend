# Observability Design: OpenTelemetry + ClickHouse + Grafana

## Overview

Add comprehensive observability to the rental platform backend: structured logging, distributed tracing, and metrics collection. All three signals flow through OpenTelemetry to ClickHouse, visualized in Grafana with pre-built dashboards.

Scope: local/dev environment only. All infrastructure runs in docker-compose alongside the existing PostgreSQL.

## Architecture

```
FastAPI App (host)
  ├─ OTel SDK (traces, logs, metrics)
  └─ OTLP gRPC ──→ OTel Collector (docker, :4317)
                      └─ clickhouse-exporter ──→ ClickHouse (docker, :8123/:9000)
                                                    ↑
                                              Grafana (docker, :3001)
```

- App runs on host, sends OTLP to `localhost:4317`
- OTel Collector (`otel/opentelemetry-collector-contrib`) receives all signals, batches, and exports to ClickHouse
- ClickHouse stores traces, logs, and metrics in auto-created tables (`otel_traces`, `otel_logs`, `otel_metrics`)
- Grafana (`grafana/grafana` with `grafana-clickhouse-datasource` plugin) reads from ClickHouse

## Frontend Tracing Contract

**W3C Trace Context propagation**: FastAPI auto-instrumentation parses incoming `traceparent` / `tracestate` headers and continues the trace. If no `traceparent` is sent, a new trace is created.

**`X-Trace-Id` response header**: Every response includes `X-Trace-Id` with the 32-hex-character trace ID. Frontend can display this in error toasts or attach to bug reports.

**CORS**: `X-Trace-Id` added to `expose_headers` so browsers can read it.

**Contract summary**:
- Frontend MAY send `traceparent` header → backend continues that trace
- Backend ALWAYS returns `X-Trace-Id` header
- Trace ID format: 32 lowercase hex characters (W3C standard)

## Infrastructure

### New docker-compose services (added to `docker-compose.dev.yml`)

**OTel Collector**:
- Image: `otel/opentelemetry-collector-contrib`
- Ports: 4317 (gRPC), 4318 (HTTP)
- Config: `config/otel-collector.yaml`

**ClickHouse**:
- Image: `clickhouse/clickhouse-server`
- Ports: 8123 (HTTP), 9000 (native)
- Persistent volume for data
- Tables auto-created by clickhouse-exporter

**Grafana**:
- Image: `grafana/grafana`
- Port: 3001 (avoids frontend conflict on 3000)
- Plugin: `grafana-clickhouse-datasource` via `GF_INSTALL_PLUGINS`
- Anonymous auth enabled (no login for dev)
- Provisioned datasource and dashboards on startup

### Collector config (`config/otel-collector.yaml`)

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

## App-Level OTel Setup

### Package structure

```
app/observability/
├── __init__.py          # Public API: setup_observability(), shutdown_observability()
├── tracing.py           # TracerProvider, SpanProcessor, OTLP exporter, @traced decorator
├── logging.py           # OTel log bridge, context injection filter
├── metrics.py           # MeterProvider, OTLP exporter, app-level meters
├── events.py            # Business event emitter
└── middleware.py         # TraceIDMiddleware (X-Trace-Id header)
```

### Initialization

Called from `lifespan` in `main.py`:

```python
@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    setup_observability(application)
    async with RegisterTortoise(...):
        await _seed_categories()
        yield
    shutdown_observability()
```

`setup_observability()`:
1. Create `Resource` with `service.name`, `service.version`, `deployment.environment`
2. Configure `TracerProvider` with `BatchSpanProcessor` + OTLP gRPC exporter
3. Configure `MeterProvider` with `PeriodicExportingMetricReader` (30s) + OTLP gRPC exporter
4. Configure `LoggerProvider` with `BatchLogRecordProcessor` + OTLP gRPC exporter
5. Install auto-instrumentations: `FastAPIInstrumentor`, `AsyncPGInstrumentor`
6. Attach OTel `LoggingHandler` to stdlib root logger
7. Add `TraceIDMiddleware` to the FastAPI app

`shutdown_observability()`:
- Call `force_flush()` then `shutdown()` on all three providers

### Python dependencies

```
opentelemetry-api
opentelemetry-sdk
opentelemetry-exporter-otlp-proto-grpc
opentelemetry-instrumentation-fastapi
opentelemetry-instrumentation-asyncpg
opentelemetry-instrumentation-logging
python-json-logger
```

### Configuration

New section in `config/base.yaml`:

```yaml
observability:
  enabled: true
  otlp_endpoint: "localhost:4317"
  service_name: "rental-platform"
  log_level: INFO
  metrics_export_interval_seconds: 30
```

Disabled in `config/test.yaml`:

```yaml
observability:
  enabled: false
```

## Middleware & Trace ID Header

`TraceIDMiddleware` in `app/observability/middleware.py`:

```python
class TraceIDMiddleware:
    async def __call__(self, request, call_next):
        response = await call_next(request)
        span = trace.get_current_span()
        if span.get_span_context().is_valid:
            trace_id = format(span.get_span_context().trace_id, '032x')
            response.headers["X-Trace-Id"] = trace_id
        return response
```

CORS config updated — add `X-Trace-Id` to `expose_headers`.

## Structured Logging

### Two handlers on stdlib root logger

1. **Console handler** — `StreamHandler` with default human-readable formatter (for terminal)
2. **OTel handler** — `LoggingHandler` from `opentelemetry-instrumentation-logging` (bridges records to OTel pipeline)

The OTel handler automatically attaches `trace_id`, `span_id`, `trace_flags` to every log record emitted within an active span.

### Context injection

`RequestContextFilter` — a `logging.Filter` that enriches log records from a `ContextVar`:

```python
class RequestContextFilter(logging.Filter):
    def filter(self, record):
        ctx = context_var.get()
        record.user_id = ctx.user_id
        record.org_id = ctx.org_id
        return True
```

The `ContextVar` is populated by middleware from the authenticated user and path parameters. Service code gets ambient context without manual plumbing.

### Business events

Thin helper in `app/observability/events.py`:

```python
def emit_event(event: str, **attributes: str | int | None) -> None:
    logger.info(event, extra={"event.name": event, **attributes})
```

### Event catalog

| Event | Attributes | Source |
|-------|-----------|--------|
| `user.registered` | `user_id` | users/service |
| `user.authenticated` | `user_id` | users/service |
| `user.auth_failed` | `email` (redacted) | users/service |
| `organization.created` | `org_id`, `inn` | organizations/service |
| `organization.verified` | `org_id` | organizations/service |
| `membership.invited` | `org_id`, `user_id`, `role` | organizations/service |
| `membership.accepted` | `org_id`, `user_id` | organizations/service |
| `listing.created` | `listing_id`, `org_id` | listings/service |
| `listing.status_changed` | `listing_id`, `old_status`, `new_status` | listings/service |
| `order.created` | `order_id`, `listing_id`, `user_id` | orders/service |
| `order.status_changed` | `order_id`, `old_status`, `new_status` | orders/service |
| `dadata.called` | `inn`, `success`, `duration_ms` | organizations/service |

### Log levels convention

- `ERROR` — unhandled exceptions, external service failures
- `WARNING` — auth failures, permission denials, client validation errors
- `INFO` — business events, request lifecycle
- `DEBUG` — DB queries (via asyncpg auto-instrumentation), detailed internal state

## Service Instrumentation

### `@traced` decorator

In `app/observability/tracing.py`:

```python
def traced(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span(
            f"{func.__module__}.{func.__name__}",
            attributes=_extract_span_attributes(func, args, kwargs),
        ):
            return await func(*args, **kwargs)
    return wrapper
```

### Automatic span attributes

`_extract_span_attributes` inspects parameter names and values to set:
- `app.user_id` — from `user_id` param or `User` model
- `app.org_id` — from `org_id` / `organization_id` param
- `app.order_id` — from `order_id` param
- `app.listing_id` — from `listing_id` param
- Key fields from Pydantic schemas (e.g., `data.inn` from `OrganizationCreate`)

### Exception recording

The `start_as_current_span` context manager auto-records exceptions: sets `otel.status_code = ERROR` and `exception.*` span attributes.

### Applied to all service functions

Every public function in:
- `app/users/service.py`
- `app/organizations/service.py`
- `app/listings/service.py`
- `app/orders/service.py`

### Resulting trace shape

Example: `POST /orders/`

```
[FastAPI] POST /orders/
  └─ [Service] app.orders.service.create_order
       ├─ [asyncpg] SELECT ... FROM listings
       ├─ [asyncpg] INSERT INTO orders
       └─ [Log] order.created
```

## Metrics

### Auto-collected (from instrumentors)

- `http.server.request.duration` — histogram by method, route, status
- `http.server.active_requests` — concurrent requests gauge
- `db.client.connections.usage` — connection pool utilization

### Custom application metrics

Defined in `app/observability/metrics.py`:

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `app.orders.created` | Counter | `org_id`, `listing_id` | Order volume |
| `app.orders.transitions` | Counter | `from_status`, `to_status` | State machine flow |
| `app.auth.attempts` | Counter | `result` (success/failed/suspended) | Auth monitoring |
| `app.dadata.requests` | Counter | `success` (true/false) | External API reliability |
| `app.dadata.duration` | Histogram | — | External API latency |
| `app.business_events` | Counter | `event_name` | Unified event rate |

Export interval: 30 seconds (configurable).

## Grafana Dashboards

Four JSON dashboards provisioned in `config/grafana/dashboards/`:

### 1. API Overview (home)
- Request rate by endpoint (time series)
- Latency p50/p95/p99 by endpoint (time series)
- Error rate by status code (time series)
- Active requests gauge
- Top 10 slowest endpoints table

### 2. Traces Explorer
- Search by trace ID, user ID, org ID, order ID
- Recent traces table with duration, status, endpoint
- Trace waterfall view (via ClickHouse datasource trace linking)
- Error traces filter

### 3. Business Events
- Order creation rate over time
- Order state machine transitions breakdown
- Auth success/failure ratio
- Organization registrations over time
- Dadata call success rate and latency
- Event rate by `event_name`

### 4. Infrastructure
- DB connection pool usage
- OTel Collector health
- Log volume by level over time
- Error log stream (latest ERROR/WARNING entries)

### Provisioning

- `config/grafana/provisioning/datasources/clickhouse.yaml` — ClickHouse datasource → `clickhouse:8123`
- `config/grafana/provisioning/dashboards/default.yaml` — points to dashboards directory
- Dashboard JSON files committed to repo
- `task infra:up` brings Grafana up fully configured
