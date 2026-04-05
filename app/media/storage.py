import asyncio
import logging

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class StorageClient:
    def __init__(
        self,
        endpoint_url: str,
        presigned_endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._presigned_endpoint_url = presigned_endpoint_url or endpoint_url
        self._bucket = bucket
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self._config = Config(signature_version="s3v4")

    @property
    def bucket(self) -> str:
        return self._bucket

    async def ensure_bucket(self, *, retries: int = 5, delay: float = 2.0) -> None:
        for attempt in range(1, retries + 1):
            try:
                async with self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config) as s3:
                    try:
                        await s3.head_bucket(Bucket=self._bucket)
                    except ClientError:
                        await s3.create_bucket(Bucket=self._bucket)
            except ClientError as exc:
                if attempt == retries:
                    raise
                logger.warning("Storage not ready (attempt %d/%d): %s", attempt, retries, exc)
                await asyncio.sleep(delay)
            else:
                return

    async def generate_upload_url(self, key: str, content_type: str, expires: int) -> str:
        async with self._session.client("s3", endpoint_url=self._presigned_endpoint_url, config=self._config) as s3:
            url: str = await s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expires,
            )
            return url

    async def generate_download_url(self, key: str, expires: int) -> str:
        async with self._session.client("s3", endpoint_url=self._presigned_endpoint_url, config=self._config) as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires,
            )
            return url

    async def download(self, key: str) -> bytes:
        async with self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config) as s3:
            response = await s3.get_object(Bucket=self._bucket, Key=key)
            data: bytes = await response["Body"].read()
            return data

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        async with self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config) as s3:
            await s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    async def delete(self, key: str) -> None:
        async with self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config) as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def delete_prefix(self, prefix: str) -> None:
        async with self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config) as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                contents = page.get("Contents", [])
                if contents:
                    delete_objects = [{"Key": obj["Key"]} for obj in contents]
                    await s3.delete_objects(Bucket=self._bucket, Delete={"Objects": delete_objects})

    async def exists(self, key: str) -> bool:
        async with self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config) as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
            except ClientError:
                return False
            else:
                return True


# --- Singleton for FastAPI dependency injection ---

_instance: StorageClient | None = None


def init_storage(
    endpoint_url: str,
    presigned_endpoint_url: str,
    access_key: str,
    secret_key: str,
    bucket: str,
) -> StorageClient:
    global _instance  # noqa: PLW0603
    _instance = StorageClient(
        endpoint_url=endpoint_url,
        presigned_endpoint_url=presigned_endpoint_url,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
    )
    return _instance


def get_storage() -> StorageClient:
    if _instance is None:
        raise RuntimeError("StorageClient not initialized — call init_storage() first")
    return _instance
