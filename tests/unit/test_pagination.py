import json
from base64 import b64decode, b64encode
from datetime import UTC, datetime

import pytest

from app.core.pagination import CursorParams, decode_cursor, encode_cursor


class TestCursorEncoding:
    def test_encode_decode_roundtrip(self) -> None:
        values = {"updated_at": datetime(2026, 3, 30, 12, 0, 0, tzinfo=UTC), "id": "ABC123"}
        cursor = encode_cursor(values)
        decoded = decode_cursor(cursor)
        assert decoded["updated_at"] == values["updated_at"]
        assert decoded["id"] == values["id"]

    def test_encode_produces_base64(self) -> None:
        values = {"updated_at": datetime(2026, 1, 1, tzinfo=UTC), "id": "X"}
        cursor = encode_cursor(values)
        raw = json.loads(b64decode(cursor).decode())
        assert "updated_at" in raw
        assert "id" in raw

    def test_decode_invalid_base64_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor("not-valid-base64!!!")

    def test_decode_invalid_json_raises(self) -> None:
        bad = b64encode(b"not json").decode()
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor(bad)

    def test_decode_non_dict_json_raises(self) -> None:
        bad = b64encode(b"[1, 2, 3]").decode()
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor(bad)

    def test_decode_preserves_non_string_values(self) -> None:
        cursor = encode_cursor({"count": 42, "id": "ABC123"})
        decoded = decode_cursor(cursor)
        assert decoded["count"] == 42
        assert decoded["id"] == "ABC123"


class TestCursorParams:
    def test_defaults(self) -> None:
        params = CursorParams()
        assert params.cursor is None
        assert params.limit == 20

    def test_limit_capped_at_100(self) -> None:
        with pytest.raises(ValueError):
            CursorParams(limit=101)

    def test_limit_minimum_1(self) -> None:
        with pytest.raises(ValueError):
            CursorParams(limit=0)
