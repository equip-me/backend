from fastapi import FastAPI
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource

from app.core.config import get_settings
from app.observability.logs import setup_logging, shutdown_logging
from app.observability.metrics import setup_metrics, shutdown_metrics
from app.observability.tracing import setup_tracing, shutdown_tracing


def setup_observability(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.observability.enabled:
        return

    resource = Resource.create(
        {
            "service.name": settings.observability.service_name,
            "deployment.environment": settings.app_env,
        }
    )
    endpoint = settings.observability.otlp_endpoint
    obs = settings.observability

    setup_tracing(resource, endpoint)
    setup_metrics(resource, endpoint, obs.metrics_export_interval_seconds * 1000)
    setup_logging(resource, endpoint, obs.console_log_level, obs.otel_log_level)

    FastAPIInstrumentor.instrument_app(app)
    AsyncPGInstrumentor().instrument()


def shutdown_observability() -> None:
    settings = get_settings()
    if not settings.observability.enabled:
        return
    shutdown_tracing()
    shutdown_metrics()
    shutdown_logging()
