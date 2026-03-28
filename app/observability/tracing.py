import inspect
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.observability.context import request_context

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

# Param name → span attribute key for object parameters (e.g. `user: User`)
_PARAM_NAME_MODEL_MAP: dict[str, str] = {
    "user": "app.user_id",
    "org": "app.org_id",
    "organization": "app.org_id",
    "listing": "app.listing_id",
    "order": "app.order_id",
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
            attr_key = _MODEL_ATTR_MAP.get(class_name) or _PARAM_NAME_MODEL_MAP.get(name)
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


def traced[**P, R](func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]:
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
