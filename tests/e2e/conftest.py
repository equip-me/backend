"""E2E tests — real database, real storage, real services. Only time is mocked."""

import datetime
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_today() -> Generator[MagicMock]:
    """Patch ``date.today`` to return a controllable date.

    Usage::

        def test_something(mock_today):
            mock_today.today.return_value = datetime.date(2026, 4, 1)
            ...
    """
    with patch("app.orders.service.date") as mock_date:
        mock_date.today.return_value = datetime.datetime.now(tz=datetime.UTC).date()
        mock_date.side_effect = datetime.date
        yield mock_date
