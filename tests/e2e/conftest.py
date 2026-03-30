"""E2E tests — real database, real storage, real services. Only time is mocked."""

import datetime
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_today() -> Generator[MagicMock]:
    """Patch ``datetime.now`` in the orders service to return a controllable datetime.

    The service calls ``datetime.now(UTC).date()`` for both order-creation
    validation and auto-transition evaluation.  We mock ``datetime.now`` so
    that ``.date()`` on the result returns the date we set.

    Usage::

        def test_something(mock_today):
            mock_today.return_value = datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC)
            ...
    """
    real_datetime = datetime.datetime

    with patch("app.orders.service.datetime") as mock_dt:
        mock_dt.now.return_value = real_datetime.now(tz=datetime.UTC)
        # Keep side_effect so datetime(...) constructor calls still work
        mock_dt.side_effect = real_datetime
        mock_dt.UTC = datetime.UTC
        yield mock_dt
