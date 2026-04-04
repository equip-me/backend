import pytest

import app.media.storage as storage_mod


def test_get_storage_before_init_raises() -> None:
    original = storage_mod._instance
    storage_mod._instance = None
    try:
        with pytest.raises(RuntimeError, match="not initialized"):
            storage_mod.get_storage()
    finally:
        storage_mod._instance = original


def test_init_storage_and_get_storage() -> None:
    original = storage_mod._instance
    try:
        storage_mod._instance = None
        client = storage_mod.init_storage(
            endpoint_url="http://localhost:9000",
            presigned_endpoint_url="http://localhost:9000",
            access_key="test",
            secret_key="test",
            bucket="test-bucket",
        )
        assert client is not None
        assert storage_mod.get_storage() is client
        assert client.bucket == "test-bucket"
    finally:
        storage_mod._instance = original
