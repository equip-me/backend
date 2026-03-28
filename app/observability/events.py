import logging
from typing import Any

from app.observability.metrics import business_events_counter

logger = logging.getLogger("app.events")


def emit_event(event: str, **attributes: Any) -> None:
    extra: dict[str, Any] = {"event.name": event, **attributes}
    logger.info(event, extra=extra)
    business_events_counter.add(1, {"event_name": event})
