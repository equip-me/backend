"""DB tests — requires PostgreSQL, external services are mocked."""

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import app
from app.media.storage import get_storage
from app.organizations.dependencies import get_dadata_client

DADATA_PARTY_RESPONSE: dict[str, Any] = {
    "value": 'ООО "РОГА И КОПЫТА"',
    "data": {
        "inn": "7707083893",
        "name": {
            "short_with_opf": 'ООО "Рога и копыта"',
            "full_with_opf": 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "РОГА И КОПЫТА"',
        },
        "state": {
            "registration_date": 1029456000000,
        },
        "address": {
            "value": "г Москва, ул Ленина, д 1",
        },
        "management": {
            "name": "Иванов Иван Иванович",
        },
        "okved": "62.01",
    },
}


@pytest.fixture(autouse=True)
def mock_dadata() -> Generator[MagicMock]:
    mock = MagicMock()
    mock.find_by_id.return_value = [DADATA_PARTY_RESPONSE]
    app.dependency_overrides[get_dadata_client] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_dadata_client, None)


@pytest.fixture(autouse=True)
def mock_storage() -> Generator[AsyncMock]:
    mock = AsyncMock()
    mock.generate_upload_url.return_value = "https://minio:9000/bucket/pending/test/file?X-Amz-Signature=abc"
    mock.generate_download_url.return_value = "https://minio:9000/bucket/media/test/file?X-Amz-Signature=abc"
    mock.exists.return_value = True
    app.dependency_overrides[get_storage] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_storage, None)


@pytest.fixture(autouse=True)
def mock_arq_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()

    async def _mock_get_pool() -> AsyncMock:
        return mock_pool

    monkeypatch.setattr("app.worker.settings.get_arq_pool", _mock_get_pool)
