import json
from base64 import b64decode, b64encode
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from tortoise.expressions import Q
from tortoise.queryset import QuerySet


class CursorParams(BaseModel):
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class PaginatedResponse[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


def encode_cursor(values: dict[str, Any]) -> str:
    """Encode cursor values as a base64 JSON string."""
    serialized: dict[str, Any] = {}
    for key, val in values.items():
        if isinstance(val, datetime):
            serialized[key] = val.isoformat()
        elif isinstance(val, UUID):
            serialized[key] = str(val)
        else:
            serialized[key] = val
    return b64encode(json.dumps(serialized).encode()).decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode a base64 JSON cursor string back to values."""
    try:
        raw = json.loads(b64decode(cursor).decode())
    except Exception as exc:
        msg = "Invalid cursor"
        raise ValueError(msg) from exc
    if not isinstance(raw, dict):
        msg = "Invalid cursor"
        raise ValueError(msg)  # noqa: TRY004
    result: dict[str, Any] = {}
    for key, val in raw.items():
        if isinstance(val, str):
            try:
                result[key] = datetime.fromisoformat(val)
            except ValueError:
                result[key] = val
        else:
            result[key] = val
    return result


def _parse_ordering(ordering: tuple[str, ...]) -> list[tuple[str, bool]]:
    """Parse ordering tuple into (field_name, is_descending) pairs."""
    parsed: list[tuple[str, bool]] = []
    for field in ordering:
        if field.startswith("-"):
            parsed.append((field[1:], True))
        else:
            parsed.append((field, False))
    return parsed


async def paginate(
    queryset: QuerySet[Any],
    params: CursorParams,
    ordering: tuple[str, ...] = ("-updated_at", "-id"),
) -> tuple[list[Any], str | None, bool]:
    """Apply cursor pagination to a queryset.

    Returns (items, next_cursor, has_more).
    The cursor encodes the fields from the ordering tuple.
    """
    parsed = _parse_ordering(ordering)

    if params.cursor is not None:
        cursor_data = decode_cursor(params.cursor)
        # Build compound WHERE for cursor position.
        # For 2-field ordering (f1 DESC, f2 DESC):
        #   WHERE f1 < v1 OR (f1 = v1 AND f2 < v2)
        filters = Q()
        for i, (field, desc) in enumerate(parsed):
            eq_conditions: dict[str, Any] = {}
            for j in range(i):
                prev_field, _ = parsed[j]
                eq_conditions[prev_field] = cursor_data[prev_field]
            op = "lt" if desc else "gt"
            eq_conditions[f"{field}__{op}"] = cursor_data[field]
            filters |= Q(**eq_conditions)
        queryset = queryset.filter(filters)

    queryset = queryset.order_by(*ordering)
    items: list[Any] = await queryset.limit(params.limit + 1)

    has_more = len(items) > params.limit
    if has_more:
        items = items[: params.limit]

    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        cursor_values: dict[str, Any] = {}
        for field, _ in parsed:
            cursor_values[field] = getattr(last, field)
        next_cursor = encode_cursor(cursor_values)

    return items, next_cursor, has_more


class OrderingParams(Protocol):
    """Protocol for dependency classes produced by ordering_dependency."""

    ordering: tuple[str, ...]


def ordering_dependency(
    allowed_fields: dict[str, str],
    default: str,
) -> type[OrderingParams]:
    """Create a FastAPI dependency class for validating and parsing order_by query params.

    Args:
        allowed_fields: Mapping of client-facing field names to ORM field names.
        default: Default ordering field (prefix with '-' for descending).

    Returns:
        A class usable as a FastAPI dependency with an `ordering` property.

    """
    _allowed = allowed_fields
    _default = default

    class _OrderingParams:
        def __init__(self, order_by: str | None = None) -> None:
            raw = order_by if order_by is not None else _default
            descending = raw.startswith("-")
            field_name = raw[1:] if descending else raw

            if field_name not in _allowed:
                allowed_list = ", ".join(sorted(_allowed))
                raise RequestValidationError(
                    [
                        {
                            "loc": ("query", "order_by"),
                            "msg": f"Invalid order_by field '{field_name}'. Allowed: {allowed_list}",
                            "type": "value_error",
                        },
                    ],
                )

            model_field = _allowed[field_name]
            prefix = "-" if descending else ""
            tiebreaker = "-id" if descending else "id"
            self.ordering: tuple[str, ...] = (f"{prefix}{model_field}", tiebreaker)

    return _OrderingParams
