"""Unit tests — no database, no external services. All dependencies are mocked.

Override the root conftest autouse DB fixtures so unit tests
run without a database connection.
"""

from collections.abc import AsyncGenerator

import pytest


@pytest.fixture(scope="session", autouse=True)
async def initialize_db() -> AsyncGenerator[None]:
    """No-op: unit tests do not need a database."""
    yield


@pytest.fixture(autouse=True)
async def truncate_tables() -> None:
    """No-op: unit tests do not need table truncation."""
