from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.media.storage import StorageClient

INTERNAL_ENDPOINT = "http://minio:9000"
PUBLIC_ENDPOINT = "https://s3.example.com"


def test_presigned_endpoint_url_stored() -> None:
    client = StorageClient(
        endpoint_url=INTERNAL_ENDPOINT,
        presigned_endpoint_url=PUBLIC_ENDPOINT,
        access_key="test",
        secret_key="test",
        bucket="test",
    )
    assert client._presigned_endpoint_url == PUBLIC_ENDPOINT


def test_presigned_endpoint_url_defaults_to_endpoint_url() -> None:
    client = StorageClient(
        endpoint_url=INTERNAL_ENDPOINT,
        presigned_endpoint_url="",
        access_key="test",
        secret_key="test",
        bucket="test",
    )
    assert client._presigned_endpoint_url == INTERNAL_ENDPOINT


def _make_client() -> StorageClient:
    return StorageClient(
        endpoint_url=INTERNAL_ENDPOINT,
        presigned_endpoint_url=PUBLIC_ENDPOINT,
        access_key="test",
        secret_key="test",
        bucket="test-bucket",
    )


@pytest.mark.anyio
async def test_generate_upload_url_uses_presigned_endpoint() -> None:
    """Presigned upload URLs must be signed against the public endpoint, not the internal one."""
    client = _make_client()

    fake_url = f"{PUBLIC_ENDPOINT}/test-bucket/key.jpg?X-Amz-Signature=abc"
    mock_s3 = AsyncMock()
    mock_s3.generate_presigned_url = AsyncMock(return_value=fake_url)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch.object(client._session, "client", return_value=mock_ctx) as mock_client_call:
        url = await client.generate_upload_url("key.jpg", "image/jpeg", 3600)

    mock_client_call.assert_called_once_with("s3", endpoint_url=PUBLIC_ENDPOINT, config=client._config)
    assert url == fake_url
    assert INTERNAL_ENDPOINT not in url


@pytest.mark.anyio
async def test_generate_download_url_uses_presigned_endpoint() -> None:
    """Presigned download URLs must be signed against the public endpoint, not the internal one."""
    client = _make_client()

    fake_url = f"{PUBLIC_ENDPOINT}/test-bucket/key.jpg?X-Amz-Signature=abc"
    mock_s3 = AsyncMock()
    mock_s3.generate_presigned_url = AsyncMock(return_value=fake_url)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch.object(client._session, "client", return_value=mock_ctx) as mock_client_call:
        url = await client.generate_download_url("key.jpg", 3600)

    mock_client_call.assert_called_once_with("s3", endpoint_url=PUBLIC_ENDPOINT, config=client._config)
    assert url == fake_url
    assert INTERNAL_ENDPOINT not in url
