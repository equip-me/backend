import logging
from collections.abc import Callable
from typing import cast

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
            record.user_id = ctx.user_id
            record.org_id = ctx.org_id
            record.order_id = ctx.order_id
            record.listing_id = ctx.listing_id
        else:
            record.user_id = ""
            record.org_id = ""
            record.order_id = ""
            record.listing_id = ""
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

    # Suppress noisy third-party loggers
    for name in ("botocore", "aiobotocore", "urllib3", "s3transfer"):
        logging.getLogger(name).setLevel(logging.WARNING)


def shutdown_logging() -> None:
    if _provider is not None:
        _provider.force_flush()
        cast("Callable[[], None]", _provider.shutdown)()
