# Media & S3 Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add media support (photos, videos, documents) with S3-compatible storage, async processing via ARQ workers, and automatic cleanup.

**Architecture:** Presigned URL upload to MinIO, confirmation triggers ARQ job, worker converts photos to WebP variants (Pillow) and videos to WebM (ffmpeg), documents are stored as-is. Orphan cleanup via ARQ cron. Generic `owner_type`+`owner_id` association on Media model.

**Tech Stack:** aioboto3 (S3 client), ARQ (async task queue, Redis), Pillow (image processing), ffmpeg-python (video processing), MinIO (S3-compatible storage)

**Spec:** `docs/superpowers/specs/2026-03-29-media-s3-integration-design.md`

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `app/media/__init__.py` | Module init |
| `app/media/models.py` | Media Tortoise model |
| `app/media/schemas.py` | Pydantic request/response schemas |
| `app/media/router.py` | FastAPI endpoints (upload-url, confirm, status, delete, retry) |
| `app/media/service.py` | Business logic (upload, confirm, attach, detach, delete) |
| `app/media/storage.py` | S3-compatible StorageClient wrapper over aioboto3 + `get_storage()` FastAPI dependency |
| `app/media/processing.py` | Photo (Pillow) and video (ffmpeg) processing functions |
| `app/media/worker.py` | ARQ worker definition, job handlers, orphan cleanup cron |
| `app/media/dependencies.py` | Media resolution and permission checking |
| `tests/test_media.py` | Integration tests for media endpoints |
| `tests/test_media_processing.py` | Unit tests for photo/video/document processing |

### Modified files

| File | Changes |
|------|---------|
| `pyproject.toml` | Add aioboto3, arq, Pillow, ffmpeg-python deps + mypy overrides |
| `docker-compose.dev.yml` | Add MinIO + Redis services |
| `docker-compose.test.yml` | Add MinIO + Redis on test ports |
| `docker-compose.prod.yml` | Add MinIO + Redis services |
| `Dockerfile` | Install ffmpeg in runtime stage |
| `Taskfile.yml` | Add `worker` task |
| `config/base.yaml` | Add storage, media, worker sections |
| `config/dev.yaml` | Add storage credentials |
| `config/test.yaml` | Add storage/worker with test ports |
| `config/prod.yaml` | Add storage endpoint override |
| `.env.example` | Add STORAGE__ACCESS_KEY, STORAGE__SECRET_KEY |
| `app/core/config.py` | Add StorageSettings, MediaSettings, WorkerSettings |
| `app/core/enums.py` | Add MediaKind, MediaOwnerType, MediaContext, MediaStatus |
| `app/core/database.py` | Register `app.media.models` |
| `app/main.py` | Register media router, init StorageClient in lifespan |
| `app/users/schemas.py` | Add profile_photo to UserCreate, UserUpdate, UserRead |
| `app/users/service.py` | Handle profile photo attach/detach |
| `app/users/router.py` | Pass photo_id through |
| `app/organizations/schemas.py` | Add photo to OrganizationCreate, OrganizationRead |
| `app/organizations/service.py` | Handle photo attach, pre-delete media cleanup |
| `app/organizations/router.py` | Add photo update endpoint |
| `app/listings/schemas.py` | Add media arrays to ListingCreate, ListingUpdate, ListingRead |
| `app/listings/service.py` | Handle media attach/detach on create/update/delete |
| `app/listings/router.py` | Pass media IDs through |
| `tests/conftest.py` | Add mock_storage fixture, media table to truncation list |

---

## Task 1: Infrastructure Setup

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker-compose.dev.yml`
- Modify: `docker-compose.test.yml`
- Modify: `docker-compose.prod.yml`
- Modify: `Dockerfile`
- Modify: `Taskfile.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add Python dependencies**

```bash
cd /Users/khamitovdr/equipment-sharing-backend-v2
poetry add aioboto3 arq Pillow ffmpeg-python
```

- [ ] **Step 2: Add mypy overrides for new deps in pyproject.toml**

Add after the existing `grpc.*` override block:

```toml
[[tool.mypy.overrides]]
module = ["aioboto3.*", "aiobotocore.*", "boto3.*", "botocore.*"]
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = ["arq.*"]
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = ["ffmpeg.*"]
ignore_missing_imports = true
```

- [ ] **Step 3: Add MinIO + Redis to docker-compose.dev.yml**

Add before the `volumes:` section:

```yaml
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
```

Add `minio_data:` and `redis_data:` to the `volumes:` section.

- [ ] **Step 4: Add MinIO + Redis to docker-compose.test.yml**

```yaml
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_USER: rental
      POSTGRES_PASSWORD: rental
      POSTGRES_DB: rental_test
    ports:
      - "5433:5432"

  minio:
    image: minio/minio
    command: server /data --console-address ":9003"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9002:9000"
      - "9003:9001"

  redis:
    image: redis:7-alpine
    ports:
      - "6380:6379"
```

- [ ] **Step 5: Add MinIO + Redis to docker-compose.prod.yml**

Add services (no exposed ports, internal network only):

```yaml
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    volumes:
      - minio_data:/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
```

Add `minio_data:` and `redis_data:` to volumes. Update app service environment:

```yaml
      STORAGE__ENDPOINT_URL: http://minio:9000
      STORAGE__ACCESS_KEY: ${MINIO_ROOT_USER}
      STORAGE__SECRET_KEY: ${MINIO_ROOT_PASSWORD}
      WORKER__REDIS_URL: redis://redis:6379
```

Add worker service:

```yaml
  worker:
    image: rental-platform:${APP_VERSION:-latest}
    environment:
      APP_ENV: prod
      DATABASE__PASSWORD: ${POSTGRES_PASSWORD}
      STORAGE__ENDPOINT_URL: http://minio:9000
      STORAGE__ACCESS_KEY: ${MINIO_ROOT_USER}
      STORAGE__SECRET_KEY: ${MINIO_ROOT_PASSWORD}
      WORKER__REDIS_URL: redis://redis:6379
    depends_on:
      - db
      - minio
      - redis
    command: python -m app.media.worker
```

- [ ] **Step 6: Install ffmpeg in Dockerfile**

Add to the runtime stage, before `WORKDIR /app`:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 7: Add worker task to Taskfile.yml**

Add after the `run` task:

```yaml
  worker:
    desc: Start the ARQ media worker
    cmds:
      - poetry run python -m app.media.worker {{.CLI_ARGS}}
```

- [ ] **Step 8: Update .env.example**

Add:

```
STORAGE__ACCESS_KEY=minioadmin
STORAGE__SECRET_KEY=minioadmin
```

- [ ] **Step 9: Restart infrastructure and verify**

```bash
task infra:reset && task infra:up
task test:reset && task test:up
```

Verify MinIO console is accessible at `http://localhost:9001` (dev) and Redis responds:

```bash
docker exec rental-dev-redis-1 redis-cli ping
```

Expected: `PONG`

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml poetry.lock docker-compose.dev.yml docker-compose.test.yml docker-compose.prod.yml Dockerfile Taskfile.yml .env.example
git commit -m "chore: add media infrastructure (MinIO, Redis, ffmpeg, Python deps)"
```

---

## Task 2: Configuration Models

**Files:**
- Modify: `app/core/config.py`
- Modify: `config/base.yaml`
- Modify: `config/dev.yaml`
- Modify: `config/test.yaml`
- Modify: `config/prod.yaml`
- Test: `tests/test_config.py` (new)

- [ ] **Step 1: Write failing test for new config sections**

Create `tests/test_config.py`:

```python
import os

from app.core.config import Settings


def test_storage_settings_loaded() -> None:
    os.environ["APP_ENV"] = "test"
    settings = Settings()
    assert settings.storage.endpoint_url == "http://localhost:9002"
    assert settings.storage.bucket == "rental-media-test"
    assert settings.storage.presigned_url_expiry_seconds == 3600


def test_media_settings_loaded() -> None:
    os.environ["APP_ENV"] = "test"
    settings = Settings()
    assert settings.media.max_photo_size_mb == 20
    assert settings.media.orphan_cleanup_after_hours == 24
    assert "profile" in settings.media.photo_variant_sets
    assert "listing" in settings.media.photo_variant_sets
    profile_variants = settings.media.photo_variant_sets["profile"]
    assert len(profile_variants) == 2
    assert profile_variants[0]["name"] == "medium"


def test_worker_settings_loaded() -> None:
    os.environ["APP_ENV"] = "test"
    settings = Settings()
    assert settings.worker.redis_url == "redis://localhost:6380"
    assert settings.worker.max_concurrent_jobs == 10
```

- [ ] **Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/test_config.py -v
```

Expected: FAIL — `StorageSettings` does not exist.

- [ ] **Step 3: Add config models to app/core/config.py**

Add these classes before the `Settings` class:

```python
class StorageSettings(BaseModel):
    endpoint_url: str = "http://localhost:9000"
    bucket: str = "rental-media"
    presigned_url_expiry_seconds: int = 3600
    access_key: str = ""
    secret_key: str = ""


class PhotoVariant(BaseModel):
    name: str
    max_width: int
    quality: int


class VideoVariant(BaseModel):
    name: str
    max_height: int
    video_bitrate: str
    audio: bool = True
    max_duration_seconds: int | None = None


class MediaSettings(BaseModel):
    max_photo_size_mb: int = 20
    max_video_size_mb: int = 500
    max_document_size_mb: int = 50
    allowed_photo_types: list[str] = ["image/jpeg", "image/png", "image/webp", "image/heic"]
    allowed_video_types: list[str] = ["video/mp4", "video/quicktime", "video/webm"]
    allowed_document_types: list[str] = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
        "text/csv",
    ]
    orphan_cleanup_after_hours: int = 24
    orphan_cleanup_interval_minutes: int = 60
    photo_variant_sets: dict[str, list[dict[str, int | str]]] = {}
    video_variant_sets: dict[str, list[dict[str, int | str | bool]]] = {}
    listing_limits_max_photos: int = 20
    listing_limits_max_videos: int = 5
    listing_limits_max_documents: int = 10


class WorkerSettings(BaseModel):
    redis_url: str = "redis://localhost:6379"
    max_concurrent_jobs: int = 10
```

Add fields to the `Settings` class:

```python
    storage: StorageSettings = StorageSettings()
    media: MediaSettings = MediaSettings()
    worker: WorkerSettings = WorkerSettings()
```

- [ ] **Step 4: Add config sections to config/base.yaml**

Append to `config/base.yaml`:

```yaml
storage:
  endpoint_url: "http://localhost:9000"
  bucket: "rental-media"
  presigned_url_expiry_seconds: 3600

media:
  max_photo_size_mb: 20
  max_video_size_mb: 500
  max_document_size_mb: 50
  allowed_photo_types:
    - "image/jpeg"
    - "image/png"
    - "image/webp"
    - "image/heic"
  allowed_video_types:
    - "video/mp4"
    - "video/quicktime"
    - "video/webm"
  allowed_document_types:
    - "application/pdf"
    - "application/msword"
    - "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    - "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    - "text/plain"
    - "text/csv"
  orphan_cleanup_after_hours: 24
  orphan_cleanup_interval_minutes: 60
  photo_variant_sets:
    profile:
      - { name: "medium", max_width: 600, quality: 80 }
      - { name: "small", max_width: 200, quality: 75 }
    listing:
      - { name: "large", max_width: 1200, quality: 85 }
      - { name: "medium", max_width: 600, quality: 80 }
      - { name: "small", max_width: 200, quality: 75 }
  video_variant_sets:
    listing:
      - { name: "full", max_height: 720, video_bitrate: "1.5M", audio: true }
      - { name: "preview", max_height: 480, video_bitrate: "500k", audio: false, max_duration_seconds: 10 }
  listing_limits_max_photos: 20
  listing_limits_max_videos: 5
  listing_limits_max_documents: 10

worker:
  redis_url: "redis://localhost:6379"
  max_concurrent_jobs: 10
```

- [ ] **Step 5: Add test overrides to config/test.yaml**

Append:

```yaml
storage:
  endpoint_url: "http://localhost:9002"
  bucket: "rental-media-test"
  access_key: "minioadmin"
  secret_key: "minioadmin"

worker:
  redis_url: "redis://localhost:6380"
```

- [ ] **Step 6: Add dev overrides to config/dev.yaml**

Append:

```yaml
storage:
  access_key: "minioadmin"
  secret_key: "minioadmin"
```

- [ ] **Step 7: Add prod override to config/prod.yaml**

Append:

```yaml
storage:
  endpoint_url: "http://minio:9000"

worker:
  redis_url: "redis://redis:6379"
```

- [ ] **Step 8: Run test to verify it passes**

```bash
poetry run pytest tests/test_config.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 9: Run lint and typecheck**

```bash
task lint:fix && task typecheck
```

- [ ] **Step 10: Commit**

```bash
git add app/core/config.py config/ tests/test_config.py
git commit -m "feat(media): add storage, media, and worker configuration models"
```

---

## Task 3: Media Enums + Model + Migration

**Files:**
- Modify: `app/core/enums.py`
- Create: `app/media/__init__.py`
- Create: `app/media/models.py`
- Modify: `app/core/database.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add media enums to app/core/enums.py**

Append:

```python
class MediaKind(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"


class MediaOwnerType(StrEnum):
    USER = "user"
    ORGANIZATION = "organization"
    LISTING = "listing"


class MediaContext(StrEnum):
    USER_PROFILE = "user_profile"
    ORG_PROFILE = "org_profile"
    LISTING = "listing"


class MediaStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
```

- [ ] **Step 2: Create app/media/__init__.py**

```python
```

Empty file.

- [ ] **Step 3: Create app/media/models.py**

```python
from typing import Any
from uuid import uuid4

from tortoise import fields
from tortoise.models import Model

from app.core.enums import MediaContext, MediaKind, MediaOwnerType, MediaStatus


class Media(Model):
    id = fields.UUIDField(primary_key=True, default=uuid4)
    uploaded_by: Any = fields.ForeignKeyField("models.User", related_name="uploaded_media")
    owner_type = fields.CharEnumField(MediaOwnerType, max_length=20, null=True)
    owner_id = fields.CharField(max_length=6, null=True)
    kind = fields.CharEnumField(MediaKind, max_length=20)
    context = fields.CharEnumField(MediaContext, max_length=20)
    status = fields.CharEnumField(MediaStatus, max_length=20, default=MediaStatus.PENDING_UPLOAD)
    original_filename = fields.CharField(max_length=255)
    content_type = fields.CharField(max_length=128)
    file_size = fields.IntField()
    position = fields.SmallIntField(default=0)
    upload_key = fields.CharField(max_length=512)
    variants: Any = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)
    processed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "media"
        ordering = ["position", "-created_at"]
```

- [ ] **Step 4: Register model in app/core/database.py**

Add `"app.media.models"` to the `MODELS` list:

```python
MODELS = [
    "app.users.models",
    "app.organizations.models",
    "app.listings.models",
    "app.orders.models",
    "app.media.models",
]
```

- [ ] **Step 5: Add media table to test truncation in tests/conftest.py**

Add `"media"` to the beginning of `_TEST_TABLES` (before "orders", since media has no FK dependencies):

```python
_TEST_TABLES = (
    "media",
    "orders",
    "listings",
    "listing_categories",
    "memberships",
    "organization_contacts",
    "payment_details",
    "organizations",
    "users",
)
```

- [ ] **Step 6: Write DB test for Media CRUD**

Add to `tests/test_media.py` (new file):

```python
from uuid import uuid4

from app.core.enums import MediaContext, MediaKind, MediaStatus
from app.media.models import Media
from app.users.models import User


async def test_create_media_record(create_user: ...) -> None:
    user_data, _ = await create_user()
    user = await User.get(id=user_data["id"])

    media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="photo.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=f"pending/{uuid4()}/photo.jpg",
    )

    fetched = await Media.get(id=media.id)
    assert fetched.kind == MediaKind.PHOTO
    assert fetched.context == MediaContext.USER_PROFILE
    assert fetched.status == MediaStatus.PENDING_UPLOAD
    assert fetched.owner_type is None
    assert fetched.owner_id is None
    assert fetched.variants == {}


async def test_media_owner_assignment() -> None:
    from app.core.enums import MediaOwnerType

    user = await User.create(
        id="TSTU01",
        email="media-test@example.com",
        hashed_password="x",
        phone="+79991234567",
        name="Test",
        surname="User",
    )
    media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.LISTING,
        original_filename="listing.jpg",
        content_type="image/jpeg",
        file_size=2048,
        upload_key="pending/test/listing.jpg",
    )

    media.owner_type = MediaOwnerType.LISTING
    media.owner_id = "LST001"
    media.status = MediaStatus.READY
    media.variants = {"large": "media/test/large.webp", "medium": "media/test/medium.webp"}
    await media.save()

    fetched = await Media.get(id=media.id)
    assert fetched.owner_type == MediaOwnerType.LISTING
    assert fetched.owner_id == "LST001"
    assert fetched.status == MediaStatus.READY
    assert fetched.variants["large"] == "media/test/large.webp"
```

- [ ] **Step 7: Run tests**

```bash
poetry run pytest tests/test_media.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 8: Run lint and typecheck**

```bash
task lint:fix && task typecheck
```

- [ ] **Step 9: Commit**

```bash
git add app/core/enums.py app/media/ app/core/database.py tests/conftest.py tests/test_media.py
git commit -m "feat(media): add Media model with enums and DB registration"
```

---

## Task 4: Storage Client

**Files:**
- Create: `app/media/storage.py`
- Modify: `app/main.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Write failing test for StorageClient**

Add to `tests/test_media.py`:

```python
import pytest

from app.media.storage import StorageClient


@pytest.fixture
async def storage() -> StorageClient:
    from app.core.config import get_settings

    settings = get_settings()
    client = StorageClient(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        bucket=settings.storage.bucket,
    )
    await client.ensure_bucket()
    return client


async def test_storage_upload_and_download(storage: StorageClient) -> None:
    key = "test/hello.txt"
    await storage.upload(key, b"hello world", "text/plain")

    assert await storage.exists(key)

    data = await storage.download(key)
    assert data == b"hello world"

    await storage.delete(key)
    assert not await storage.exists(key)


async def test_storage_presigned_upload_url(storage: StorageClient) -> None:
    url = await storage.generate_upload_url("test/upload.txt", "text/plain", expires=60)
    assert "test/upload.txt" in url
    assert "X-Amz-Signature" in url


async def test_storage_presigned_download_url(storage: StorageClient) -> None:
    key = "test/download.txt"
    await storage.upload(key, b"download me", "text/plain")

    url = await storage.generate_download_url(key, expires=60)
    assert "test/download.txt" in url
    assert "X-Amz-Signature" in url

    await storage.delete(key)


async def test_storage_delete_prefix(storage: StorageClient) -> None:
    await storage.upload("test/prefix/a.txt", b"a", "text/plain")
    await storage.upload("test/prefix/b.txt", b"b", "text/plain")
    await storage.upload("test/other/c.txt", b"c", "text/plain")

    await storage.delete_prefix("test/prefix/")

    assert not await storage.exists("test/prefix/a.txt")
    assert not await storage.exists("test/prefix/b.txt")
    assert await storage.exists("test/other/c.txt")

    await storage.delete("test/other/c.txt")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/test_media.py::test_storage_upload_and_download -v
```

Expected: FAIL — `app.media.storage` not found.

- [ ] **Step 3: Implement StorageClient**

Create `app/media/storage.py`:

```python
import aioboto3
from botocore.config import Config


class StorageClient:
    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._bucket = bucket
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self._config = Config(signature_version="s3v4")

    @property
    def bucket(self) -> str:
        return self._bucket

    async def ensure_bucket(self) -> None:
        async with self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config) as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except s3.exceptions.ClientError:
                await s3.create_bucket(Bucket=self._bucket)

    async def generate_upload_url(self, key: str, content_type: str, expires: int) -> str:
        async with self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config) as s3:
            url: str = await s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expires,
            )
            return url

    async def generate_download_url(self, key: str, expires: int) -> str:
        async with self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config) as s3:
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
            except s3.exceptions.ClientError:
                return False
            else:
                return True


# --- Singleton for FastAPI dependency injection ---

_instance: StorageClient | None = None


def init_storage(
    endpoint_url: str,
    access_key: str,
    secret_key: str,
    bucket: str,
) -> StorageClient:
    global _instance  # noqa: PLW0603
    _instance = StorageClient(
        endpoint_url=endpoint_url,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
    )
    return _instance


def get_storage() -> StorageClient:
    assert _instance is not None, "StorageClient not initialized — call init_storage() first"
    return _instance
```

**Important:** `get_storage` lives in `app/media/storage.py` (not `app/main.py`) to avoid circular imports, since `app/main.py` imports all routers.

- [ ] **Step 4: Run storage tests**

```bash
poetry run pytest tests/test_media.py -k "storage" -v
```

Expected: 4 tests PASS (requires test MinIO running via `task test:up`).

- [ ] **Step 5: Add StorageClient initialization to app/main.py lifespan**

Add import at top:

```python
from app.media.storage import init_storage
```

Inside the `lifespan` function, after `_seed_categories()` and before `yield`:

```python
        settings = get_settings()
        storage = init_storage(
            endpoint_url=settings.storage.endpoint_url,
            access_key=settings.storage.access_key,
            secret_key=settings.storage.secret_key,
            bucket=settings.storage.bucket,
        )
        await storage.ensure_bucket()
```

- [ ] **Step 6: Run lint and typecheck**

```bash
task lint:fix && task typecheck
```

- [ ] **Step 7: Commit**

```bash
git add app/media/storage.py app/main.py tests/test_media.py
git commit -m "feat(media): add S3-compatible StorageClient with MinIO support"
```

---

## Task 5: Media Schemas + Upload URL Endpoint

**Files:**
- Create: `app/media/schemas.py`
- Create: `app/media/service.py`
- Create: `app/media/router.py`
- Create: `app/media/dependencies.py`
- Modify: `app/main.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Write failing test for upload URL endpoint**

Add fixture to `tests/conftest.py`:

```python
from unittest.mock import AsyncMock


@pytest.fixture(autouse=True)
def mock_storage() -> Generator[AsyncMock]:
    mock = AsyncMock()
    mock.generate_upload_url.return_value = "https://minio:9000/bucket/pending/test/file?X-Amz-Signature=abc"
    mock.generate_download_url.return_value = "https://minio:9000/bucket/media/test/file?X-Amz-Signature=abc"
    mock.exists.return_value = True
    app.dependency_overrides[get_storage] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_storage, None)
```

Add to `tests/test_media.py`:

```python
from httpx import AsyncClient


async def test_request_upload_url(client: AsyncClient, create_user: ...) -> None:
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "avatar.jpg",
            "content_type": "image/jpeg",
            "file_size": 1_000_000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "media_id" in data
    assert "upload_url" in data
    assert "expires_in" in data


async def test_upload_url_rejects_invalid_content_type(client: AsyncClient, create_user: ...) -> None:
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "malware.exe",
            "content_type": "application/x-msdownload",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400


async def test_upload_url_rejects_oversized_file(client: AsyncClient, create_user: ...) -> None:
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "huge.jpg",
            "content_type": "image/jpeg",
            "file_size": 100_000_000,  # 100 MB > 20 MB limit
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400


async def test_upload_url_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "avatar.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
    )

    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/test_media.py::test_request_upload_url -v
```

Expected: FAIL — 404 (route not registered).

- [ ] **Step 3: Create app/media/schemas.py**

```python
from uuid import UUID

from pydantic import BaseModel

from app.core.enums import MediaContext, MediaKind, MediaStatus


class UploadUrlRequest(BaseModel):
    kind: MediaKind
    context: MediaContext
    filename: str
    content_type: str
    file_size: int


class UploadUrlResponse(BaseModel):
    media_id: UUID
    upload_url: str
    expires_in: int


class MediaStatusResponse(BaseModel):
    id: UUID
    status: MediaStatus
    kind: MediaKind
    context: MediaContext
    original_filename: str
    variants: dict[str, str]


class MediaPhotoRead(BaseModel):
    id: UUID
    large_url: str | None = None
    medium_url: str | None = None
    small_url: str | None = None
    position: int = 0


class MediaVideoRead(BaseModel):
    id: UUID
    full_url: str | None = None
    preview_url: str | None = None
    position: int = 0


class MediaDocumentRead(BaseModel):
    id: UUID
    url: str
    filename: str
    file_size: int
    position: int = 0


class ProfilePhotoRead(BaseModel):
    id: UUID
    medium_url: str
    small_url: str
```

- [ ] **Step 4: Create app/media/service.py**

```python
from uuid import uuid4

from app.core.config import get_settings
from app.core.enums import MediaKind, MediaStatus
from app.core.exceptions import AppValidationError
from app.media.models import Media
from app.media.schemas import UploadUrlRequest, UploadUrlResponse
from app.media.storage import StorageClient
from app.observability.tracing import traced
from app.users.models import User


def _max_size_bytes(kind: MediaKind) -> int:
    settings = get_settings()
    mb = {
        MediaKind.PHOTO: settings.media.max_photo_size_mb,
        MediaKind.VIDEO: settings.media.max_video_size_mb,
        MediaKind.DOCUMENT: settings.media.max_document_size_mb,
    }[kind]
    return mb * 1024 * 1024


def _allowed_types(kind: MediaKind) -> list[str]:
    settings = get_settings()
    return {
        MediaKind.PHOTO: settings.media.allowed_photo_types,
        MediaKind.VIDEO: settings.media.allowed_video_types,
        MediaKind.DOCUMENT: settings.media.allowed_document_types,
    }[kind]


@traced
async def request_upload_url(
    data: UploadUrlRequest,
    user: User,
    storage: StorageClient,
) -> UploadUrlResponse:
    if data.content_type not in _allowed_types(data.kind):
        raise AppValidationError(f"Content type '{data.content_type}' is not allowed for {data.kind.value}")

    max_size = _max_size_bytes(data.kind)
    if data.file_size > max_size:
        raise AppValidationError(f"File size exceeds maximum of {max_size // (1024 * 1024)} MB for {data.kind.value}")

    media_id = uuid4()
    upload_key = f"pending/{media_id}/{data.filename}"

    media = await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=data.kind,
        context=data.context,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename=data.filename,
        content_type=data.content_type,
        file_size=data.file_size,
        upload_key=upload_key,
    )

    settings = get_settings()
    expires = settings.storage.presigned_url_expiry_seconds
    upload_url = await storage.generate_upload_url(upload_key, data.content_type, expires)

    return UploadUrlResponse(
        media_id=media.id,
        upload_url=upload_url,
        expires_in=expires,
    )
```

- [ ] **Step 5: Create app/media/dependencies.py**

```python
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Path

from app.core.dependencies import require_active_user
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.media.models import Media
from app.users.models import User


async def resolve_media(
    media_id: UUID = Path(),
) -> Media:
    media = await Media.get_or_none(id=media_id).prefetch_related("uploaded_by")
    if media is None:
        raise NotFoundError("Media not found")
    return media


async def require_media_uploader(
    media: Annotated[Media, Depends(resolve_media)],
    user: Annotated[User, Depends(require_active_user)],
) -> Media:
    uploader: User = media.uploaded_by
    if uploader.id != user.id:
        raise PermissionDeniedError("You can only manage your own uploads")
    return media
```

- [ ] **Step 6: Create app/media/router.py**

```python
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user
from app.media.storage import get_storage
from app.media import service
from app.media.schemas import UploadUrlRequest, UploadUrlResponse
from app.media.storage import StorageClient
from app.users.models import User

router = APIRouter(tags=["media"])


@router.post("/media/upload-url", response_model=UploadUrlResponse)
async def request_upload_url(
    data: UploadUrlRequest,
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UploadUrlResponse:
    return await service.request_upload_url(data, user, storage)
```

- [ ] **Step 7: Register media router in app/main.py**

Add import:

```python
from app.media.router import router as media_router
```

Add after `orders_router` inclusion:

```python
    application.include_router(media_router)
```

- [ ] **Step 8: Run tests**

```bash
poetry run pytest tests/test_media.py -k "upload_url" -v
```

Expected: 4 tests PASS.

- [ ] **Step 9: Run lint and typecheck**

```bash
task lint:fix && task typecheck
```

- [ ] **Step 10: Commit**

```bash
git add app/media/schemas.py app/media/service.py app/media/router.py app/media/dependencies.py app/main.py tests/conftest.py tests/test_media.py
git commit -m "feat(media): add upload URL endpoint with validation"
```

---

## Task 6: Confirm Endpoint

**Files:**
- Modify: `app/media/service.py`
- Modify: `app/media/router.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Write failing test for confirm endpoint**

Add to `tests/test_media.py`:

```python
async def test_confirm_upload(client: AsyncClient, create_user: ..., mock_storage: ...) -> None:
    _, token = await create_user()

    # Request upload URL
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "document",
            "context": "listing",
            "filename": "spec.pdf",
            "content_type": "application/pdf",
            "file_size": 5000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    # Confirm upload
    confirm_resp = await client.post(
        f"/media/{media_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert confirm_resp.status_code == 200
    data = confirm_resp.json()
    assert data["status"] == "processing"


async def test_confirm_rejects_non_uploader(client: AsyncClient, create_user: ..., mock_storage: ...) -> None:
    _, token1 = await create_user(email="uploader@example.com")
    _, token2 = await create_user(email="other@example.com", phone="+79001112233")

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token1}"},
    )
    media_id = resp.json()["media_id"]

    confirm_resp = await client.post(
        f"/media/{media_id}/confirm",
        headers={"Authorization": f"Bearer {token2}"},
    )

    assert confirm_resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/test_media.py::test_confirm_upload -v
```

Expected: FAIL — 404 or 405.

- [ ] **Step 3: Add confirm_upload to service**

Add to `app/media/service.py`:

```python
from app.core.exceptions import AppValidationError, NotFoundError


@traced
async def confirm_upload(
    media: Media,
    storage: StorageClient,
) -> Media:
    if media.status != MediaStatus.PENDING_UPLOAD:
        raise AppValidationError(f"Media is in '{media.status}' state, expected 'pending_upload'")

    if not await storage.exists(media.upload_key):
        raise NotFoundError("Uploaded file not found in storage")

    media.status = MediaStatus.PROCESSING
    await media.save()

    # TODO: enqueue ARQ job in Task 7
    return media
```

- [ ] **Step 4: Add confirm endpoint to router**

Add to `app/media/router.py`:

```python
from app.media.dependencies import require_media_uploader
from app.media.models import Media
from app.media.schemas import MediaStatusResponse


@router.post("/media/{media_id}/confirm", response_model=MediaStatusResponse)
async def confirm_upload(
    media: Annotated[Media, Depends(require_media_uploader)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> MediaStatusResponse:
    updated = await service.confirm_upload(media, storage)
    return MediaStatusResponse(
        id=updated.id,
        status=updated.status,
        kind=updated.kind,
        context=updated.context,
        original_filename=updated.original_filename,
        variants=updated.variants,
    )
```

- [ ] **Step 5: Run tests**

```bash
poetry run pytest tests/test_media.py -k "confirm" -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Run lint and typecheck**

```bash
task lint:fix && task typecheck
```

- [ ] **Step 7: Commit**

```bash
git add app/media/service.py app/media/router.py tests/test_media.py
git commit -m "feat(media): add upload confirmation endpoint"
```

---

## Task 7: Photo Processing + ARQ Worker

**Files:**
- Create: `app/media/processing.py`
- Create: `app/media/worker.py`
- Modify: `app/media/service.py`
- Test: `tests/test_media_processing.py`

- [ ] **Step 1: Write unit test for photo processing**

Create `tests/test_media_processing.py`:

```python
import io

from PIL import Image


def _create_test_image(width: int = 2000, height: int = 1500, fmt: str = "JPEG") -> bytes:
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


async def test_process_photo_creates_variants() -> None:
    from app.media.processing import process_photo

    original = _create_test_image(2000, 1500)
    variant_specs = [
        {"name": "large", "max_width": 1200, "quality": 85},
        {"name": "medium", "max_width": 600, "quality": 80},
        {"name": "small", "max_width": 200, "quality": 75},
    ]

    results = process_photo(original, variant_specs)

    assert len(results) == 3
    for spec in variant_specs:
        name = spec["name"]
        assert name in results
        img = Image.open(io.BytesIO(results[name]))
        assert img.format == "WEBP"
        assert img.width <= spec["max_width"]


async def test_process_photo_does_not_upscale() -> None:
    from app.media.processing import process_photo

    original = _create_test_image(100, 75)
    variant_specs = [
        {"name": "large", "max_width": 1200, "quality": 85},
        {"name": "small", "max_width": 200, "quality": 75},
    ]

    results = process_photo(original, variant_specs)

    for name in results:
        img = Image.open(io.BytesIO(results[name]))
        assert img.width <= 100


async def test_process_photo_strips_exif() -> None:
    from app.media.processing import process_photo

    img = Image.new("RGB", (800, 600), color="blue")
    from PIL.ExifTags import Base as ExifBase

    exif_data = img.getexif()
    exif_data[ExifBase.Make] = "TestCamera"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_data.tobytes())
    original = buf.getvalue()

    results = process_photo(original, [{"name": "medium", "max_width": 600, "quality": 80}])

    result_img = Image.open(io.BytesIO(results["medium"]))
    result_exif = result_img.getexif()
    assert ExifBase.Make not in result_exif
```

- [ ] **Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/test_media_processing.py::test_process_photo_creates_variants -v
```

Expected: FAIL — `process_photo` not found.

- [ ] **Step 3: Implement photo processing**

Create `app/media/processing.py`:

```python
import io

from PIL import Image, ImageOps


def process_photo(original_data: bytes, variant_specs: list[dict[str, int | str]]) -> dict[str, bytes]:
    img = Image.open(io.BytesIO(original_data))
    img = ImageOps.exif_transpose(img) or img

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    results: dict[str, bytes] = {}
    for spec in variant_specs:
        name = str(spec["name"])
        max_width = int(spec["max_width"])
        quality = int(spec["quality"])

        variant = img.copy()
        if variant.width > max_width:
            ratio = max_width / variant.width
            new_height = int(variant.height * ratio)
            variant = variant.resize((max_width, new_height), Image.LANCZOS)

        buf = io.BytesIO()
        variant.save(buf, format="WEBP", quality=quality)
        results[name] = buf.getvalue()

    return results
```

- [ ] **Step 4: Run photo processing tests**

```bash
poetry run pytest tests/test_media_processing.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Implement ARQ worker**

Create `app/media/worker.py`:

```python
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings
from app.core.enums import MediaKind, MediaStatus
from app.media.models import Media
from app.media.processing import process_photo
from app.media.storage import StorageClient

logger = logging.getLogger(__name__)


def _get_storage() -> StorageClient:
    settings = get_settings()
    return StorageClient(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        bucket=settings.storage.bucket,
    )


def _get_variant_specs(media: Media) -> list[dict[str, Any]]:
    settings = get_settings()
    context = media.context.value
    if media.kind == MediaKind.PHOTO:
        return list(settings.media.photo_variant_sets.get(context, []))
    if media.kind == MediaKind.VIDEO:
        return list(settings.media.video_variant_sets.get(context, []))
    return []


async def process_media_job(ctx: dict[str, Any], media_id: str) -> None:
    from tortoise import Tortoise

    from app.core.database import get_tortoise_config

    if not Tortoise._inited:
        await Tortoise.init(config=get_tortoise_config())

    media = await Media.get_or_none(id=UUID(media_id))
    if media is None:
        logger.error("Media %s not found", media_id)
        return

    storage = _get_storage()

    try:
        if media.kind == MediaKind.PHOTO:
            await _process_photo(media, storage)
        elif media.kind == MediaKind.VIDEO:
            await _process_video(media, storage)
        elif media.kind == MediaKind.DOCUMENT:
            await _process_document(media, storage)

        media.status = MediaStatus.READY
        media.processed_at = datetime.now(tz=UTC)
        await media.save()
        logger.info("Processed media %s (%s)", media_id, media.kind.value)

    except Exception:
        logger.exception("Failed to process media %s", media_id)
        media.status = MediaStatus.FAILED
        await media.save()
        raise


async def _process_photo(media: Media, storage: StorageClient) -> None:
    original_data = await storage.download(media.upload_key)
    variant_specs = _get_variant_specs(media)
    results = process_photo(original_data, variant_specs)

    variants: dict[str, str] = {}
    for name, data in results.items():
        key = f"media/{media.id}/{name}.webp"
        await storage.upload(key, data, "image/webp")
        variants[name] = key

    media.variants = variants
    await storage.delete(media.upload_key)


async def _process_video(media: Media, storage: StorageClient) -> None:
    # Implemented in Task 8
    pass


async def _process_document(media: Media, storage: StorageClient) -> None:
    # Implemented in Task 9
    pass


async def get_arq_pool() -> ArqRedis:
    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.worker.redis_url)
    return await create_pool(redis_settings)


class WorkerSettings:
    functions = [process_media_job]
    max_jobs = 10

    @staticmethod
    def redis_settings() -> RedisSettings:
        settings = get_settings()
        return RedisSettings.from_dsn(settings.worker.redis_url)


if __name__ == "__main__":
    import asyncio

    from arq import run_worker

    asyncio.run(run_worker(WorkerSettings))  # type: ignore[arg-type]
```

- [ ] **Step 6: Wire confirm to enqueue ARQ job**

Update `app/media/service.py` `confirm_upload` — replace the `# TODO` comment:

```python
from app.media.worker import get_arq_pool


@traced
async def confirm_upload(
    media: Media,
    storage: StorageClient,
) -> Media:
    if media.status != MediaStatus.PENDING_UPLOAD:
        raise AppValidationError(f"Media is in '{media.status}' state, expected 'pending_upload'")

    if not await storage.exists(media.upload_key):
        raise NotFoundError("Uploaded file not found in storage")

    media.status = MediaStatus.PROCESSING
    await media.save()

    pool = await get_arq_pool()
    await pool.enqueue_job("process_media_job", str(media.id))

    return media
```

- [ ] **Step 7: Run lint and typecheck**

```bash
task lint:fix && task typecheck
```

- [ ] **Step 8: Commit**

```bash
git add app/media/processing.py app/media/worker.py app/media/service.py tests/test_media_processing.py
git commit -m "feat(media): add photo processing with Pillow and ARQ worker"
```

---

## Task 8: Video Processing

**Files:**
- Modify: `app/media/processing.py`
- Modify: `app/media/worker.py`
- Test: `tests/test_media_processing.py`

- [ ] **Step 1: Write test for video processing command construction**

Add to `tests/test_media_processing.py`:

```python
from unittest.mock import patch, MagicMock


async def test_build_video_full_command() -> None:
    from app.media.processing import build_video_command

    cmd = build_video_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.webm",
        max_height=720,
        video_bitrate="1.5M",
        audio=True,
        max_duration_seconds=None,
    )
    assert "-vf" in cmd
    assert "scale=" in " ".join(cmd)
    assert "-b:v" in cmd
    assert "1.5M" in cmd
    assert "-an" not in cmd


async def test_build_video_preview_command() -> None:
    from app.media.processing import build_video_command

    cmd = build_video_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/preview.webm",
        max_height=480,
        video_bitrate="500k",
        audio=False,
        max_duration_seconds=10,
    )
    assert "-an" in cmd
    assert "-t" in cmd
    assert "10" in cmd
```

- [ ] **Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/test_media_processing.py::test_build_video_full_command -v
```

Expected: FAIL — `build_video_command` not found.

- [ ] **Step 3: Implement video processing**

Add to `app/media/processing.py`:

```python
import asyncio
import subprocess
import tempfile
from pathlib import Path


def build_video_command(
    input_path: str,
    output_path: str,
    max_height: int,
    video_bitrate: str,
    audio: bool,
    max_duration_seconds: int | None,
) -> list[str]:
    cmd = ["ffmpeg", "-y", "-i", input_path]

    if max_duration_seconds is not None:
        cmd.extend(["-t", str(max_duration_seconds)])

    cmd.extend([
        "-vf", f"scale=-2:'min({max_height},ih)'",
        "-c:v", "libvpx-vp9",
        "-b:v", video_bitrate,
    ])

    if audio:
        cmd.extend(["-c:a", "libopus", "-b:a", "128k"])
    else:
        cmd.append("-an")

    cmd.append(output_path)
    return cmd


async def process_video(
    original_data: bytes,
    variant_specs: list[dict[str, int | str | bool]],
    original_filename: str,
) -> dict[str, bytes]:
    results: dict[str, bytes] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / original_filename
        input_path.write_bytes(original_data)

        for spec in variant_specs:
            name = str(spec["name"])
            output_path = Path(tmpdir) / f"{name}.webm"

            cmd = build_video_command(
                input_path=str(input_path),
                output_path=str(output_path),
                max_height=int(spec["max_height"]),
                video_bitrate=str(spec["video_bitrate"]),
                audio=bool(spec.get("audio", True)),
                max_duration_seconds=int(spec["max_duration_seconds"]) if spec.get("max_duration_seconds") else None,
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                msg = f"ffmpeg failed for variant '{name}': {stderr.decode()}"
                raise RuntimeError(msg)

            results[name] = output_path.read_bytes()

    return results
```

- [ ] **Step 4: Wire video processing in worker**

Replace the `_process_video` placeholder in `app/media/worker.py`:

```python
async def _process_video(media: Media, storage: StorageClient) -> None:
    from app.media.processing import process_video

    original_data = await storage.download(media.upload_key)
    variant_specs = _get_variant_specs(media)
    results = await process_video(original_data, variant_specs, media.original_filename)

    variants: dict[str, str] = {}
    for name, data in results.items():
        key = f"media/{media.id}/{name}.webm"
        await storage.upload(key, data, "video/webm")
        variants[name] = key

    media.variants = variants
    await storage.delete(media.upload_key)
```

- [ ] **Step 5: Run tests**

```bash
poetry run pytest tests/test_media_processing.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 6: Run lint and typecheck**

```bash
task lint:fix && task typecheck
```

- [ ] **Step 7: Commit**

```bash
git add app/media/processing.py app/media/worker.py tests/test_media_processing.py
git commit -m "feat(media): add video processing with ffmpeg (VP9/WebM)"
```

---

## Task 9: Document Processing

**Files:**
- Modify: `app/media/worker.py`
- Test: `tests/test_media_processing.py`

- [ ] **Step 1: Write test for document processing**

Add to `tests/test_media_processing.py`:

```python
async def test_document_processing_is_passthrough() -> None:
    """Documents should be stored as-is with no transformation."""
    from app.media.processing import process_document

    original = b"%PDF-1.4 fake pdf content"
    result = process_document(original)
    assert result == original
```

- [ ] **Step 2: Implement document processing**

Add to `app/media/processing.py`:

```python
def process_document(original_data: bytes) -> bytes:
    return original_data
```

- [ ] **Step 3: Wire document processing in worker**

Replace the `_process_document` placeholder in `app/media/worker.py`:

```python
async def _process_document(media: Media, storage: StorageClient) -> None:
    from app.media.processing import process_document

    original_data = await storage.download(media.upload_key)
    processed = process_document(original_data)

    key = f"media/{media.id}/{media.original_filename}"
    await storage.upload(key, processed, media.content_type)

    media.variants = {"original": key}
    await storage.delete(media.upload_key)
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest tests/test_media_processing.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/media/processing.py app/media/worker.py tests/test_media_processing.py
git commit -m "feat(media): add document processing (passthrough)"
```

---

## Task 10: Media Status, Delete, Retry Endpoints

**Files:**
- Modify: `app/media/service.py`
- Modify: `app/media/router.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Write tests for status, delete, retry**

Add to `tests/test_media.py`:

```python
async def test_get_media_status(client: AsyncClient, create_user: ...) -> None:
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    status_resp = await client.get(
        f"/media/{media_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "pending_upload"


async def test_delete_media(client: AsyncClient, create_user: ...) -> None:
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    del_resp = await client.delete(
        f"/media/{media_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204

    # Verify it's gone
    status_resp = await client.get(
        f"/media/{media_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 404


async def test_retry_failed_media(client: AsyncClient, create_user: ...) -> None:
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    # Manually set to failed
    from app.core.enums import MediaStatus
    from app.media.models import Media
    from uuid import UUID

    await Media.filter(id=UUID(media_id)).update(status=MediaStatus.FAILED)

    retry_resp = await client.post(
        f"/media/{media_id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert retry_resp.status_code == 200
    assert retry_resp.json()["status"] == "processing"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
poetry run pytest tests/test_media.py::test_get_media_status -v
```

Expected: FAIL — 404/405.

- [ ] **Step 3: Add service functions**

Add to `app/media/service.py`:

```python
@traced
async def delete_media(media: Media, storage: StorageClient) -> None:
    await storage.delete_prefix(f"pending/{media.id}/")
    await storage.delete_prefix(f"media/{media.id}/")
    await media.delete()


@traced
async def retry_media(media: Media) -> Media:
    if media.status != MediaStatus.FAILED:
        raise AppValidationError("Only failed media can be retried")
    media.status = MediaStatus.PROCESSING
    await media.save()

    pool = await get_arq_pool()
    await pool.enqueue_job("process_media_job", str(media.id))

    return media
```

- [ ] **Step 4: Add endpoints to router**

Add to `app/media/router.py`:

```python
from fastapi.responses import Response


@router.get("/media/{media_id}/status", response_model=MediaStatusResponse)
async def get_media_status(
    media: Annotated[Media, Depends(require_media_uploader)],
) -> MediaStatusResponse:
    return MediaStatusResponse(
        id=media.id,
        status=media.status,
        kind=media.kind,
        context=media.context,
        original_filename=media.original_filename,
        variants=media.variants,
    )


@router.delete("/media/{media_id}", status_code=204)
async def delete_media(
    media: Annotated[Media, Depends(require_media_uploader)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> Response:
    await service.delete_media(media, storage)
    return Response(status_code=204)


@router.post("/media/{media_id}/retry", response_model=MediaStatusResponse)
async def retry_media(
    media: Annotated[Media, Depends(require_media_uploader)],
) -> MediaStatusResponse:
    updated = await service.retry_media(media)
    return MediaStatusResponse(
        id=updated.id,
        status=updated.status,
        kind=updated.kind,
        context=updated.context,
        original_filename=updated.original_filename,
        variants=updated.variants,
    )
```

- [ ] **Step 5: Run tests**

```bash
poetry run pytest tests/test_media.py -k "status or delete_media or retry" -v
```

Expected: 3 tests PASS.

- [ ] **Step 6: Run lint and typecheck**

```bash
task lint:fix && task typecheck
```

- [ ] **Step 7: Commit**

```bash
git add app/media/service.py app/media/router.py tests/test_media.py
git commit -m "feat(media): add status, delete, and retry endpoints"
```

---

## Task 11: User Profile Photo Integration

**Files:**
- Modify: `app/users/schemas.py`
- Modify: `app/users/service.py`
- Modify: `app/users/router.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Write tests for user profile photo**

Add to `tests/test_media.py`:

```python
from uuid import UUID, uuid4

from app.core.enums import MediaContext, MediaKind, MediaOwnerType, MediaStatus
from app.media.models import Media
from app.users.models import User


async def _create_ready_photo(user_id: str, context: str = "user_profile") -> UUID:
    """Helper: create a ready photo media record for testing."""
    user = await User.get(id=user_id)
    media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext(context),
        status=MediaStatus.READY,
        original_filename="photo.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=f"pending/{uuid4()}/photo.jpg",
        variants={"medium": f"media/{uuid4()}/medium.webp", "small": f"media/{uuid4()}/small.webp"},
    )
    return media.id


async def test_update_user_with_profile_photo(client: AsyncClient, create_user: ...) -> None:
    user_data, token = await create_user()
    photo_id = await _create_ready_photo(user_data["id"])

    resp = await client.patch(
        "/users/me",
        json={"profile_photo_id": str(photo_id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["profile_photo"] is not None
    assert "medium_url" in resp.json()["profile_photo"]
    assert "small_url" in resp.json()["profile_photo"]


async def test_user_read_includes_profile_photo(client: AsyncClient, create_user: ...) -> None:
    user_data, token = await create_user()
    photo_id = await _create_ready_photo(user_data["id"])

    await client.patch(
        "/users/me",
        json={"profile_photo_id": str(photo_id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["profile_photo"] is not None


async def test_remove_profile_photo(client: AsyncClient, create_user: ...) -> None:
    user_data, token = await create_user()
    photo_id = await _create_ready_photo(user_data["id"])

    await client.patch(
        "/users/me",
        json={"profile_photo_id": str(photo_id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.patch(
        "/users/me",
        json={"profile_photo_id": None},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["profile_photo"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
poetry run pytest tests/test_media.py::test_update_user_with_profile_photo -v
```

Expected: FAIL — `profile_photo_id` not recognized or `profile_photo` not in response.

- [ ] **Step 3: Update user schemas**

In `app/users/schemas.py`, add import and update schemas:

```python
from uuid import UUID
from app.media.schemas import ProfilePhotoRead
```

Add to `UserUpdate`:

```python
    profile_photo_id: UUID | None = None
```

Update `UserRead` to include photo:

```python
class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    phone: str
    name: str
    middle_name: str | None
    surname: str
    role: UserRole
    created_at: datetime
    profile_photo: ProfilePhotoRead | None = None
```

- [ ] **Step 4: Add media helper to service**

Create a helper function in `app/media/service.py`:

```python
from app.core.config import get_settings
from app.core.enums import MediaKind, MediaOwnerType, MediaStatus
from app.media.models import Media
from app.media.schemas import ProfilePhotoRead
from app.media.storage import StorageClient


async def get_profile_photo(owner_type: MediaOwnerType, owner_id: str, storage: StorageClient) -> ProfilePhotoRead | None:
    media = await Media.filter(
        owner_type=owner_type,
        owner_id=owner_id,
        kind=MediaKind.PHOTO,
        status=MediaStatus.READY,
    ).first()
    if media is None:
        return None

    settings = get_settings()
    expires = settings.storage.presigned_url_expiry_seconds

    medium_key = media.variants.get("medium", "")
    small_key = media.variants.get("small", "")

    return ProfilePhotoRead(
        id=media.id,
        medium_url=await storage.generate_download_url(medium_key, expires) if medium_key else "",
        small_url=await storage.generate_download_url(small_key, expires) if small_key else "",
    )


async def attach_profile_photo(
    media_id: UUID | None,
    owner_type: MediaOwnerType,
    owner_id: str,
    user: User,
    storage: StorageClient,
) -> None:
    # Detach any existing profile photo
    existing = await Media.filter(
        owner_type=owner_type,
        owner_id=owner_id,
        kind=MediaKind.PHOTO,
    ).all()
    for m in existing:
        m.owner_type = None
        m.owner_id = None
        await m.save()

    if media_id is None:
        return

    media = await Media.get_or_none(id=media_id)
    if media is None:
        raise NotFoundError("Media not found")
    if media.status != MediaStatus.READY:
        raise AppValidationError("Media is not ready")

    uploader: User = await media.uploaded_by  # type: ignore[assignment]
    if uploader.id != user.id:
        raise PermissionDeniedError("You can only attach your own uploads")
    if media.kind != MediaKind.PHOTO:
        raise AppValidationError("Only photos can be used as profile photo")

    media.owner_type = owner_type
    media.owner_id = owner_id
    await media.save()
```

Add missing imports to service.py:

```python
from uuid import UUID

from app.core.exceptions import NotFoundError, PermissionDeniedError
```

- [ ] **Step 5: Update user service**

In `app/users/service.py`, update `update_me` to handle profile photo:

```python
from app.core.enums import MediaOwnerType
from app.media import service as media_service
from app.media.storage import StorageClient


@traced
async def update_me(user: User, data: UserUpdate, storage: StorageClient) -> User:
    update_data = data.model_dump(exclude_unset=True, exclude={"password", "new_password", "profile_photo_id"})

    if data.email is not None and data.email != user.email:
        existing = await User.filter(email=data.email).exists()
        if existing:
            raise AlreadyExistsError("User with this email already exists")

    if data.password and data.new_password:
        if not verify_password(data.password, user.hashed_password):
            raise InvalidCredentialsError("Incorrect username or password")
        update_data["hashed_password"] = hash_password(data.new_password)

    for field, value in update_data.items():
        setattr(user, field, value)
    await user.save()

    if "profile_photo_id" in data.model_fields_set:
        await media_service.attach_profile_photo(
            data.profile_photo_id,
            MediaOwnerType.USER,
            user.id,
            user,
            storage,
        )

    return user
```

- [ ] **Step 6: Update user router to inject storage and build response**

In `app/users/router.py`:

```python
from app.core.enums import MediaOwnerType
from app.media.storage import get_storage
from app.media import service as media_service
from app.media.storage import StorageClient


@router.get("/users/me", response_model=UserRead)
async def get_me(
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read


@router.patch("/users/me", response_model=UserRead)
async def update_me(
    data: UserUpdate,
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    updated = await service.update_me(user, data, storage)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, updated.id, storage)
    user_read = UserRead.model_validate(updated)
    user_read.profile_photo = photo
    return user_read


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(
    user_id: str,
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    user = await service.get_by_id(user_id)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read
```

- [ ] **Step 7: Run tests**

```bash
poetry run pytest tests/test_media.py -k "profile_photo" -v
poetry run pytest tests/test_users.py -v
```

Expected: Profile photo tests PASS, existing user tests still PASS.

- [ ] **Step 8: Run lint and typecheck**

```bash
task lint:fix && task typecheck
```

- [ ] **Step 9: Commit**

```bash
git add app/users/ app/media/service.py app/media/schemas.py tests/test_media.py
git commit -m "feat(media): add user profile photo support"
```

---

## Task 12: Organization Photo Integration

**Files:**
- Modify: `app/organizations/schemas.py`
- Modify: `app/organizations/service.py`
- Modify: `app/organizations/router.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Write tests for org photo**

Add to `tests/test_media.py`:

```python
async def test_org_read_includes_photo(client: AsyncClient, create_organization: ..., mock_storage: ...) -> None:
    org_data, token = await create_organization()
    org_id = org_data["id"]

    # Create a ready photo assigned to the org
    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]
    photo_id = await _create_ready_photo(user_id, "org_profile")
    await Media.filter(id=photo_id).update(
        owner_type=MediaOwnerType.ORGANIZATION,
        owner_id=org_id,
    )

    resp = await client.get(
        f"/organizations/{org_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["photo"] is not None
    assert "medium_url" in resp.json()["photo"]


async def test_update_org_photo(client: AsyncClient, create_organization: ..., mock_storage: ...) -> None:
    org_data, token = await create_organization()
    org_id = org_data["id"]

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]
    photo_id = await _create_ready_photo(user_id, "org_profile")

    resp = await client.patch(
        f"/organizations/{org_id}/photo",
        json={"photo_id": str(photo_id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["photo"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
poetry run pytest tests/test_media.py::test_update_org_photo -v
```

Expected: FAIL.

- [ ] **Step 3: Update organization schemas**

In `app/organizations/schemas.py`, add:

```python
from uuid import UUID
from app.media.schemas import ProfilePhotoRead
```

Add to `OrganizationRead`:

```python
    photo: ProfilePhotoRead | None = None
```

Add new schema:

```python
class OrganizationPhotoUpdate(BaseModel):
    photo_id: UUID | None = None
```

- [ ] **Step 4: Update organization service**

Add function to `app/organizations/service.py`:

```python
from app.core.enums import MediaOwnerType
from app.media import service as media_service
from app.media.storage import StorageClient


@traced
async def update_org_photo(
    org: Organization,
    photo_id: UUID | None,
    user: User,
    storage: StorageClient,
) -> OrganizationRead:
    await media_service.attach_profile_photo(
        photo_id,
        MediaOwnerType.ORGANIZATION,
        org.id,
        user,
        storage,
    )
    await org.fetch_related("contacts")
    org_read = OrganizationRead.model_validate(org)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org.id, storage)
    return org_read
```

Add UUID import:

```python
from uuid import UUID, uuid4
```

Update `get_organization` and `create_organization` to include photo in response (pass storage through and add `photo` to the returned `OrganizationRead`). Follow the same pattern as user: validate, build read model, attach photo.

- [ ] **Step 5: Add photo update endpoint to org router**

Add to `app/organizations/router.py`:

```python
from app.media.storage import get_storage
from app.media.storage import StorageClient
from app.organizations.schemas import OrganizationPhotoUpdate


@router.patch("/organizations/{org_id}/photo", response_model=OrganizationRead)
async def update_org_photo(
    data: OrganizationPhotoUpdate,
    membership: Annotated[Membership, Depends(require_org_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    await membership.fetch_related("organization", "user")
    org: Organization = membership.organization
    user: User = membership.user
    return await service.update_org_photo(org, data.photo_id, user, storage)
```

- [ ] **Step 6: Run tests**

```bash
poetry run pytest tests/test_media.py -k "org" -v
poetry run pytest tests/test_organizations.py -v
```

Expected: Org photo tests PASS, existing org tests still PASS.

- [ ] **Step 7: Run lint and typecheck**

```bash
task lint:fix && task typecheck
```

- [ ] **Step 8: Commit**

```bash
git add app/organizations/ tests/test_media.py
git commit -m "feat(media): add organization photo support"
```

---

## Task 13: Listing Media Integration

**Files:**
- Modify: `app/listings/schemas.py`
- Modify: `app/listings/service.py`
- Modify: `app/listings/router.py`
- Modify: `app/media/service.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Write tests for listing media**

Add to `tests/test_media.py`:

```python
async def test_create_listing_with_media(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[...],
    mock_storage: ...,
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]

    photo_id = await _create_ready_photo(user_id, "listing")

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Excavator with photos",
            "category_id": category_id,
            "price": 5000.00,
            "photo_ids": [str(photo_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert len(data["photos"]) == 1
    assert "medium_url" in data["photos"][0]


async def test_listing_detail_includes_all_variants(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[...],
    mock_storage: ...,
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]

    # Create photo with listing variants
    user = await User.get(id=user_id)
    photo = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.LISTING,
        status=MediaStatus.READY,
        original_filename="listing.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=f"pending/{uuid4()}/listing.jpg",
        variants={
            "large": f"media/{uuid4()}/large.webp",
            "medium": f"media/{uuid4()}/medium.webp",
            "small": f"media/{uuid4()}/small.webp",
        },
    )

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Excavator detail test",
            "category_id": category_id,
            "price": 5000.00,
            "photo_ids": [str(photo.id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    listing_id = resp.json()["id"]
    detail = await client.get(f"/listings/{listing_id}")
    assert detail.status_code == 200
    photos = detail.json()["photos"]
    assert len(photos) == 1
    assert "large_url" in photos[0]
    assert "medium_url" in photos[0]
    assert "small_url" in photos[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
poetry run pytest tests/test_media.py::test_create_listing_with_media -v
```

Expected: FAIL.

- [ ] **Step 3: Update listing schemas**

In `app/listings/schemas.py`:

```python
from uuid import UUID
from app.media.schemas import MediaDocumentRead, MediaPhotoRead, MediaVideoRead
```

Add to `ListingCreate`:

```python
    photo_ids: list[UUID] = []
    video_ids: list[UUID] = []
    document_ids: list[UUID] = []
```

Add to `ListingUpdate`:

```python
    photo_ids: list[UUID] | None = None
    video_ids: list[UUID] | None = None
    document_ids: list[UUID] | None = None
```

Add to `ListingRead`:

```python
    photos: list[MediaPhotoRead] = []
    videos: list[MediaVideoRead] = []
    documents: list[MediaDocumentRead] = []
```

- [ ] **Step 4: Add listing media helpers to media service**

Add to `app/media/service.py`:

```python
from app.media.schemas import MediaDocumentRead, MediaPhotoRead, MediaVideoRead


async def attach_listing_media(
    listing_id: str,
    photo_ids: list[UUID],
    video_ids: list[UUID],
    document_ids: list[UUID],
    user: User,
    storage: StorageClient,
) -> None:
    settings = get_settings()

    if len(photo_ids) > settings.media.listing_limits_max_photos:
        raise AppValidationError(f"Maximum {settings.media.listing_limits_max_photos} photos allowed")
    if len(video_ids) > settings.media.listing_limits_max_videos:
        raise AppValidationError(f"Maximum {settings.media.listing_limits_max_videos} videos allowed")
    if len(document_ids) > settings.media.listing_limits_max_documents:
        raise AppValidationError(f"Maximum {settings.media.listing_limits_max_documents} documents allowed")

    # Detach all current media from this listing
    await Media.filter(
        owner_type=MediaOwnerType.LISTING,
        owner_id=listing_id,
    ).update(owner_type=None, owner_id=None)

    all_ids = list(photo_ids) + list(video_ids) + list(document_ids)
    for position, media_id in enumerate(all_ids):
        media = await Media.get_or_none(id=media_id)
        if media is None:
            raise NotFoundError(f"Media {media_id} not found")
        if media.status != MediaStatus.READY:
            raise AppValidationError(f"Media {media_id} is not ready")

        media.owner_type = MediaOwnerType.LISTING
        media.owner_id = listing_id
        media.position = position
        await media.save()


async def get_listing_media(
    listing_id: str,
    storage: StorageClient,
) -> tuple[list[MediaPhotoRead], list[MediaVideoRead], list[MediaDocumentRead]]:
    settings = get_settings()
    expires = settings.storage.presigned_url_expiry_seconds

    media_list = await Media.filter(
        owner_type=MediaOwnerType.LISTING,
        owner_id=listing_id,
        status=MediaStatus.READY,
    ).order_by("position", "-created_at")

    photos: list[MediaPhotoRead] = []
    videos: list[MediaVideoRead] = []
    documents: list[MediaDocumentRead] = []

    for m in media_list:
        if m.kind == MediaKind.PHOTO:
            photos.append(MediaPhotoRead(
                id=m.id,
                large_url=await storage.generate_download_url(m.variants["large"], expires) if "large" in m.variants else None,
                medium_url=await storage.generate_download_url(m.variants["medium"], expires) if "medium" in m.variants else None,
                small_url=await storage.generate_download_url(m.variants["small"], expires) if "small" in m.variants else None,
                position=m.position,
            ))
        elif m.kind == MediaKind.VIDEO:
            videos.append(MediaVideoRead(
                id=m.id,
                full_url=await storage.generate_download_url(m.variants["full"], expires) if "full" in m.variants else None,
                preview_url=await storage.generate_download_url(m.variants["preview"], expires) if "preview" in m.variants else None,
                position=m.position,
            ))
        elif m.kind == MediaKind.DOCUMENT:
            original_key = m.variants.get("original", "")
            documents.append(MediaDocumentRead(
                id=m.id,
                url=await storage.generate_download_url(original_key, expires) if original_key else "",
                filename=m.original_filename,
                file_size=m.file_size,
                position=m.position,
            ))

    return photos, videos, documents
```

- [ ] **Step 5: Update listing service**

Update `create_listing` in `app/listings/service.py` to accept and handle media IDs:

```python
from app.media import service as media_service
from app.media.storage import StorageClient


@traced
async def create_listing(
    org: Organization,
    user: User,
    data: ListingCreate,
    storage: StorageClient,
) -> ListingRead:
    category = await _validate_category(data.category_id, org)
    listing = await create_with_short_id(
        Listing,
        name=data.name,
        category=category,
        price=data.price,
        description=data.description,
        specifications=data.specifications,
        organization=org,
        added_by=user,
        with_operator=data.with_operator,
        on_owner_site=data.on_owner_site,
        delivery=data.delivery,
        installation=data.installation,
        setup=data.setup,
    )
    await listing.fetch_related("category")
    emit_event("listing.created", listing_id=listing.id, org_id=org.id)

    if data.photo_ids or data.video_ids or data.document_ids:
        await media_service.attach_listing_media(
            listing.id, data.photo_ids, data.video_ids, data.document_ids, user, storage,
        )

    listing_read = ListingRead.model_validate(listing)
    photos, videos, documents = await media_service.get_listing_media(listing.id, storage)
    listing_read.photos = photos
    listing_read.videos = videos
    listing_read.documents = documents
    return listing_read
```

Similarly update `update_listing` to handle media re-assignment when `photo_ids`/`video_ids`/`document_ids` are in the update payload.

Update `list_public_listings`, `list_org_listings`, and `get_listing` (via router) to include media in the response.

- [ ] **Step 6: Update listing router**

Update endpoints to inject storage and build responses with media. Follow the same pattern as users — inject `StorageClient`, call `media_service.get_listing_media`, attach to the response.

- [ ] **Step 7: Run tests**

```bash
poetry run pytest tests/test_media.py -k "listing" -v
poetry run pytest tests/test_listings.py -v
```

Expected: Listing media tests PASS, existing listing tests still PASS.

- [ ] **Step 8: Run lint and typecheck**

```bash
task lint:fix && task typecheck
```

- [ ] **Step 9: Commit**

```bash
git add app/listings/ app/media/service.py tests/test_media.py
git commit -m "feat(media): add listing photos, videos, and documents support"
```

---

## Task 14: Immediate Cleanup on Entity Deletion

**Files:**
- Modify: `app/media/service.py`
- Modify: `app/listings/service.py`
- Modify: `app/organizations/service.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Write tests for entity deletion cleanup**

Add to `tests/test_media.py`:

```python
async def test_delete_listing_cleans_up_media(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[...],
    mock_storage: ...,
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    user_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = user_resp.json()["id"]
    photo_id = await _create_ready_photo(user_id, "listing")

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "To be deleted",
            "category_id": category_id,
            "price": 1000.00,
            "photo_ids": [str(photo_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    listing_id = resp.json()["id"]

    del_resp = await client.delete(
        f"/organizations/{org_id}/listings/{listing_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204

    # Media record should be deleted
    media = await Media.get_or_none(id=photo_id)
    assert media is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/test_media.py::test_delete_listing_cleans_up_media -v
```

Expected: FAIL — media record still exists after listing deletion.

- [ ] **Step 3: Add cleanup function to media service**

Add to `app/media/service.py`:

```python
@traced
async def delete_entity_media(
    owner_type: MediaOwnerType,
    owner_id: str,
    storage: StorageClient,
) -> None:
    media_list = await Media.filter(owner_type=owner_type, owner_id=owner_id).all()
    for media in media_list:
        await storage.delete_prefix(f"pending/{media.id}/")
        await storage.delete_prefix(f"media/{media.id}/")
        await media.delete()
```

- [ ] **Step 4: Wire into listing deletion**

Update `delete_listing` in `app/listings/service.py`:

```python
@traced
async def delete_listing(listing: Listing, storage: StorageClient) -> None:
    await media_service.delete_entity_media(MediaOwnerType.LISTING, listing.id, storage)
    await listing.delete()
```

Update the router's `delete_listing` endpoint to inject and pass `storage`.

- [ ] **Step 5: Wire into organization pre-delete**

In `app/organizations/service.py`, when organization deletion is implemented, add pre-deletion cleanup:

```python
async def _cleanup_org_media(org: Organization, storage: StorageClient) -> None:
    """Clean up all media before org deletion (CASCADE won't trigger Python hooks)."""
    # Clean org profile photo
    await media_service.delete_entity_media(MediaOwnerType.ORGANIZATION, org.id, storage)
    # Clean all listing media
    listings = await Listing.filter(organization=org).all()
    for listing in listings:
        await media_service.delete_entity_media(MediaOwnerType.LISTING, listing.id, storage)
```

This function should be called before any org deletion operation.

- [ ] **Step 6: Run tests**

```bash
poetry run pytest tests/test_media.py -k "delete_listing_cleans" -v
poetry run pytest tests/test_listings.py -v
```

Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add app/media/service.py app/listings/service.py app/listings/router.py app/organizations/service.py tests/test_media.py
git commit -m "feat(media): add immediate cleanup on entity deletion"
```

---

## Task 15: Orphan Cleanup Cron

**Files:**
- Modify: `app/media/worker.py`
- Modify: `app/media/service.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Write test for orphan cleanup**

Add to `tests/test_media.py`:

```python
from datetime import UTC, datetime, timedelta


async def test_orphan_cleanup_deletes_old_unattached(mock_storage: ...) -> None:
    from app.media.service import cleanup_orphaned_media

    user = await User.create(
        id="ORPH01",
        email="orphan-test@example.com",
        hashed_password="x",
        phone="+79991234567",
        name="Test",
        surname="Orphan",
    )

    old_media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.READY,
        original_filename="old.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key="pending/old/old.jpg",
        variants={"medium": "media/old/medium.webp"},
    )
    # Backdate created_at to 48 hours ago
    await Media.filter(id=old_media.id).update(
        created_at=datetime.now(tz=UTC) - timedelta(hours=48),
    )

    recent_media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="recent.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key="pending/recent/recent.jpg",
    )

    deleted_count = await cleanup_orphaned_media(mock_storage, max_age_hours=24)

    assert deleted_count == 1
    assert await Media.get_or_none(id=old_media.id) is None
    assert await Media.get_or_none(id=recent_media.id) is not None


async def test_orphan_cleanup_skips_attached(mock_storage: ...) -> None:
    from app.media.service import cleanup_orphaned_media

    user = await User.create(
        id="ORPH02",
        email="orphan-attached@example.com",
        hashed_password="x",
        phone="+79001112233",
        name="Test",
        surname="Attached",
    )

    attached_media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        owner_type=MediaOwnerType.USER,
        owner_id="ORPH02",
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.READY,
        original_filename="attached.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key="pending/attached/attached.jpg",
        variants={"medium": "media/attached/medium.webp"},
    )
    await Media.filter(id=attached_media.id).update(
        created_at=datetime.now(tz=UTC) - timedelta(hours=48),
    )

    deleted_count = await cleanup_orphaned_media(mock_storage, max_age_hours=24)

    assert deleted_count == 0
    assert await Media.get_or_none(id=attached_media.id) is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
poetry run pytest tests/test_media.py::test_orphan_cleanup_deletes_old_unattached -v
```

Expected: FAIL — `cleanup_orphaned_media` not found.

- [ ] **Step 3: Implement orphan cleanup in service**

Add to `app/media/service.py`:

```python
from datetime import UTC, datetime, timedelta


@traced
async def cleanup_orphaned_media(storage: StorageClient, max_age_hours: int = 24) -> int:
    cutoff = datetime.now(tz=UTC) - timedelta(hours=max_age_hours)
    orphans = await Media.filter(
        owner_type=None,
        created_at__lt=cutoff,
    ).all()

    count = 0
    for media in orphans:
        await storage.delete_prefix(f"pending/{media.id}/")
        await storage.delete_prefix(f"media/{media.id}/")
        await media.delete()
        count += 1

    return count
```

- [ ] **Step 4: Wire as ARQ cron job**

In `app/media/worker.py`, add the cron function and update `WorkerSettings`:

```python
from arq.cron import cron


async def cleanup_orphans_cron(ctx: dict[str, Any]) -> None:
    from tortoise import Tortoise

    from app.core.database import get_tortoise_config
    from app.media.service import cleanup_orphaned_media

    if not Tortoise._inited:
        await Tortoise.init(config=get_tortoise_config())

    settings = get_settings()
    storage = _get_storage()
    deleted = await cleanup_orphaned_media(storage, settings.media.orphan_cleanup_after_hours)
    logger.info("Orphan cleanup: deleted %d media records", deleted)


class WorkerSettings:
    functions = [process_media_job]
    cron_jobs = [
        cron(cleanup_orphans_cron, minute={0}),  # Run at the top of every hour
    ]
    max_jobs = 10

    @staticmethod
    def redis_settings() -> RedisSettings:
        settings = get_settings()
        return RedisSettings.from_dsn(settings.worker.redis_url)
```

- [ ] **Step 5: Run tests**

```bash
poetry run pytest tests/test_media.py -k "orphan" -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Run full test suite**

```bash
task ci
```

Expected: All checks (lint + typecheck + test) PASS.

- [ ] **Step 7: Commit**

```bash
git add app/media/service.py app/media/worker.py tests/test_media.py
git commit -m "feat(media): add orphan cleanup cron job"
```

---

## Task 16: Update business-logic.md

**Files:**
- Modify: `docs/business-logic.md`

- [ ] **Step 1: Add media section to business-logic.md**

Add a new section covering:
- Media entity definition (kind, context, status, variants)
- Upload flow (presigned URL → confirm → process)
- Entity media associations (user profile photo, org photo, listing media)
- Processing rules (photo → WebP variants, video → WebM variants, documents as-is)
- Cleanup rules (immediate on entity delete, orphan cron)
- Permission rules (uploader-only for management, entity owner for attachment)

- [ ] **Step 2: Commit**

```bash
git add docs/business-logic.md
git commit -m "docs: add media and file upload section to business-logic.md"
```

---

## Summary

| Task | Component | New Files | Test Type |
|------|-----------|-----------|-----------|
| 1 | Infrastructure | — | Manual verification |
| 2 | Configuration | `tests/test_config.py` | Unit |
| 3 | Media Model | `app/media/models.py` | DB |
| 4 | Storage Client | `app/media/storage.py` | Integration (MinIO) |
| 5 | Upload URL Endpoint | `app/media/schemas.py`, `router.py`, `service.py`, `dependencies.py` | Integration |
| 6 | Confirm Endpoint | — | Integration |
| 7 | Photo Processing + Worker | `app/media/processing.py`, `worker.py` | Unit |
| 8 | Video Processing | — | Unit |
| 9 | Document Processing | — | Unit |
| 10 | Status/Delete/Retry | — | Integration |
| 11 | User Profile Photo | — | Integration |
| 12 | Org Photo | — | Integration |
| 13 | Listing Media | — | Integration |
| 14 | Entity Deletion Cleanup | — | Integration |
| 15 | Orphan Cleanup | — | DB |
| 16 | Business Logic Docs | — | — |
