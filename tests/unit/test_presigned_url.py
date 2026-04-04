from app.media.storage import StorageClient


def test_presigned_endpoint_url_stored() -> None:
    client = StorageClient(
        endpoint_url="http://minio:9000",
        presigned_endpoint_url="https://s3.example.com",
        access_key="test",
        secret_key="test",
        bucket="test",
    )
    assert client._presigned_endpoint_url == "https://s3.example.com"


def test_presigned_endpoint_url_defaults_to_endpoint_url() -> None:
    client = StorageClient(
        endpoint_url="http://minio:9000",
        presigned_endpoint_url="",
        access_key="test",
        secret_key="test",
        bucket="test",
    )
    assert client._presigned_endpoint_url == "http://minio:9000"
