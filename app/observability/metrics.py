from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

_provider: MeterProvider | None = None

_meter = metrics.get_meter("rental-platform")

# Counters
orders_created = _meter.create_counter("app.orders.created", description="Number of orders created")
order_transitions = _meter.create_counter("app.orders.transitions", description="Order status transitions")
auth_attempts = _meter.create_counter("app.auth.attempts", description="Authentication attempts")
dadata_requests = _meter.create_counter("app.dadata.requests", description="Dadata API requests")
business_events_counter = _meter.create_counter("app.business_events", description="Business events emitted")

# Histograms
dadata_duration = _meter.create_histogram(
    "app.dadata.duration",
    description="Dadata API call duration",
    unit="ms",
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
