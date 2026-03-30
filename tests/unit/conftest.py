"""Unit tests — no database, no external services. All dependencies are mocked.

Override the root conftest autouse DB fixtures so unit tests
run without a database connection.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
async def initialize_db() -> None:
    """No-op: unit tests do not need a database."""


@pytest.fixture(autouse=True)
async def truncate_tables() -> None:
    """No-op: unit tests do not need table truncation."""
