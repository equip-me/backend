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
