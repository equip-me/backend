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
