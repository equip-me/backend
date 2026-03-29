# Media & S3 Integration Design

## Overview

Add media support (photos, videos, documents) to the rental platform with S3-compatible storage, async processing via ARQ workers, and automatic cleanup of unused uploads.

### Entities with media

| Entity | Media types | Photo variants |
|--------|-------------|----------------|
| User | Profile photo (0-1) | medium, small |
| Organization | Profile photo (0-1) | medium, small |
| Listing | Photos (0-N), Videos (0-N), Documents (0-N) | large, medium, small |

### Video variants

| Variant | Resolution | Bitrate | Audio | Duration |
|---------|-----------|---------|-------|----------|
| full | 720p max | 1.5 Mbps | yes | original |
| preview | 480p max | 500 Kbps | no | first 10s |

### Format conversions

- Photos: any supported input -> WebP
- Videos: any supported input -> WebM (VP9 + Opus)
- Documents: stored as-is (PDF, DOCX, XLSX, TXT, CSV, etc.)

---

## Data Model

### Enums

```python
class MediaKind(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"

class MediaOwnerType(str, Enum):
    USER = "user"
    ORGANIZATION = "organization"
    LISTING = "listing"

class MediaContext(str, Enum):
    USER_PROFILE = "user_profile"
    ORG_PROFILE = "org_profile"
    LISTING = "listing"

class MediaStatus(str, Enum):
    PENDING_UPLOAD = "pending_upload"   # Presigned URL issued, awaiting client upload
    PROCESSING = "processing"           # ARQ worker converting/resizing
    READY = "ready"                     # All variants generated, usable
    FAILED = "failed"                   # Processing failed after retries
```

### Media model

UUID primary key (internal model, not user-facing).

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `uploaded_by` | FK -> User | Who uploaded; for permission checks + orphan tracking |
| `owner_type` | CharEnum(MediaOwnerType), nullable | null = unattached (orphan candidate) |
| `owner_id` | CharField(6), nullable | Short ID of owning entity |
| `kind` | CharEnum(MediaKind) | photo, video, document |
| `context` | CharEnum(MediaContext) | Determines variant set for processing (user_profile, org_profile, listing) |
| `status` | CharEnum(MediaStatus) | Processing lifecycle |
| `original_filename` | CharField(255) | Client's original filename |
| `content_type` | CharField(128) | MIME type |
| `file_size` | IntField | Bytes, as declared by client |
| `position` | SmallIntField, default=0 | Ordering for listing media |
| `upload_key` | CharField(512) | S3 key where client uploads |
| `variants` | JSONField, default={} | `{"large": "s3-key", "medium": "s3-key", ...}` |
| `created_at` | DatetimeField(auto_now_add) | For orphan TTL calculation |
| `processed_at` | DatetimeField, nullable | When processing completed |

### Design decisions

**Generic `owner_type` + `owner_id` instead of nullable FKs:**
- Clean null = unattached semantics for uploads not yet assigned to an entity
- Avoids 3 nullable FK columns where exactly 0 or 1 is set
- Simple orphan query: `WHERE owner_type IS NULL AND created_at < cutoff`
- Tradeoff: no DB-level CASCADE; deletion handled in service layer with orphan cleanup as safety net

**`variants` as JSON instead of a separate table:**
- Variants are always fetched together with the media record
- Small, predictable structure; never queried independently

---

## Storage Layer

### S3 abstraction

`app/media/storage.py` — thin async wrapper over `aioboto3`. Works with any S3-compatible provider (MinIO, AWS S3, Cloudflare R2).

```python
class StorageClient:
    generate_upload_url(key, content_type, expires) -> str
    generate_download_url(key, expires) -> str
    download(key) -> bytes
    upload(key, data, content_type) -> None
    delete(key) -> None
    delete_prefix(prefix) -> None   # Bulk cleanup
    exists(key) -> bool
```

Initialized at app startup (lifespan), injected via FastAPI dependency.

### S3 key structure

```
{bucket}/
  pending/{media_id}/{original_filename}     # Presigned upload target
  media/{media_id}/large.webp                # Processed photo variants
  media/{media_id}/medium.webp
  media/{media_id}/small.webp
  media/{media_id}/full.webm                 # Processed video variants
  media/{media_id}/preview.webm
  media/{media_id}/{original_filename}       # Documents (no processing)
```

`pending/` holds raw uploads. After processing, variants go to `media/` and `pending/` file is deleted. Documents move directly from `pending/` to `media/`.

---

## Configuration

### YAML config additions

```yaml
# config/base.yaml
storage:
  endpoint_url: "http://localhost:9000"
  bucket: "rental-media"
  presigned_url_expiry_seconds: 3600

media:
  max_photo_size_mb: 20
  max_video_size_mb: 500
  max_document_size_mb: 50
  allowed_photo_types: ["image/jpeg", "image/png", "image/webp", "image/heic"]
  allowed_video_types: ["video/mp4", "video/quicktime", "video/webm"]
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
  listing_limits:
    max_photos: 20
    max_videos: 5
    max_documents: 10

worker:
  redis_url: "redis://localhost:6379"
  max_concurrent_jobs: 10
```

### Secrets (env vars only)

- `STORAGE__ACCESS_KEY`
- `STORAGE__SECRET_KEY`

### Docker-compose additions (all three envs)

```yaml
minio:
  image: minio/minio
  command: server /data --console-address ":9001"
  ports:
    - "9000:9000"    # S3 API
    - "9001:9001"    # Console UI
  environment:
    MINIO_ROOT_USER: minioadmin
    MINIO_ROOT_PASSWORD: minioadmin
  volumes:
    - minio_data:/data

redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
```

Test env uses different ports (same pattern as test DB on port 5433): MinIO on 9002/9003, Redis on 6380.

### New Python dependencies

- `aioboto3` — async S3 client
- `arq` — async Redis task queue
- `Pillow` — image processing
- `ffmpeg-python` — ffmpeg wrapper (ffmpeg binary installed in Docker image)

---

## Upload & Processing Flow

### Sequence

1. Client calls `POST /media/upload-url` with `kind`, `context`, `filename`, `content_type`, `file_size`
2. Backend validates permissions, file type, file size against config limits
3. Backend creates `Media` record with `status=pending_upload`, generates presigned PUT URL
4. Returns `{ media_id, upload_url, expires_in }`
5. Client uploads directly to MinIO/S3 via presigned URL
6. Client calls `POST /media/{media_id}/confirm`
7. Backend verifies file exists in S3, updates `status=processing`, enqueues ARQ job
8. Returns updated media record

### ARQ worker processing

**Photos (Pillow):**
1. Download from `pending/{media_id}/{filename}`
2. Open with Pillow, auto-orient (EXIF rotation)
3. Strip EXIF metadata (privacy)
4. For each variant in the context's variant set:
   - Resize to `max_width` maintaining aspect ratio (only downscale, never upscale)
   - Convert to WebP at configured quality
   - Upload to `media/{media_id}/{variant_name}.webp`
5. Delete `pending/` file
6. Update DB: `status=ready`, populate `variants` JSON

**Videos (ffmpeg):**
1. Download from `pending/{media_id}/{filename}`
2. `full` variant: transcode to WebM (VP9 + Opus), scale to `max_height`, target bitrate
3. `preview` variant: lower resolution/bitrate, strip audio, trim to `max_duration_seconds`
4. Delete `pending/` file, update DB

**Documents:**
1. Move from `pending/{media_id}/{filename}` to `media/{media_id}/{filename}`
2. Update DB: `status=ready`, `variants={"original": "media/{id}/{filename}"}`

### Error handling

- ARQ retries failed jobs up to 3 times with exponential backoff
- After retries exhausted: `status=failed`, original file kept in `pending/` for inspection
- Failed media can be retried via `POST /media/{media_id}/retry`

---

## API Endpoints

### New media endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/media/upload-url` | Authenticated | Request presigned upload URL |
| `POST` | `/media/{media_id}/confirm` | Uploader only | Confirm upload, trigger processing |
| `GET` | `/media/{media_id}/status` | Uploader only | Poll processing status |
| `DELETE` | `/media/{media_id}` | Uploader or entity owner | Delete media + S3 files |
| `POST` | `/media/{media_id}/retry` | Uploader only | Re-enqueue failed processing |

### Upload URL request params

| Param | Type | Purpose |
|-------|------|---------|
| `kind` | photo / video / document | What's being uploaded |
| `context` | user_profile / org_profile / listing | Determines variant set |
| `filename` | string | Original filename |
| `content_type` | string | Validated against allowed types for this kind |
| `file_size` | int (bytes) | Validated against max size for this kind |

### Modified entity endpoints

**Users:**
- `POST /users/` — new optional `profile_photo_id: UUID | None`
- `PATCH /users/me` — new optional `profile_photo_id: UUID | None` (null removes photo)
- `GET /users/me`, `GET /users/{id}` — response includes:
  ```json
  { "profile_photo": { "id": "uuid", "medium_url": "...", "small_url": "..." } }
  ```

**Organizations:**
- `POST /organizations/` — new optional `photo_id: UUID | None`
- `PATCH /organizations/{org_id}/photo` (admin only) — update org photo
- `GET /organizations/{id}` — response includes:
  ```json
  { "photo": { "id": "uuid", "medium_url": "...", "small_url": "..." } }
  ```

**Listings:**
- `POST /organizations/{org_id}/listings/` — new optional `photo_ids: list[UUID]`, `video_ids: list[UUID]`, `document_ids: list[UUID]`
- `PATCH /organizations/{org_id}/listings/{id}` — same fields; replaces the full set (removed IDs get detached -> orphan cleanup)
- `GET /listings/{id}` (detail) — all variants for all media:
  ```json
  {
    "photos": [{"id": "uuid", "large_url": "...", "medium_url": "...", "small_url": "...", "position": 0}],
    "videos": [{"id": "uuid", "full_url": "...", "preview_url": "...", "position": 0}],
    "documents": [{"id": "uuid", "url": "...", "filename": "report.pdf", "file_size": 12345, "position": 0}]
  }
  ```
- `GET /listings/` (catalog) — `medium_url` for all photos and `preview_url` for all videos per listing (frontend handles lazy-loading in carousel)

### Attachment validation rules

- Media must be `status=ready`
- Media must be `uploaded_by` the requesting user (or org member for org/listing context)
- Media `kind` must match the field (no video as profile photo)
- User/org profile: attaching a new photo detaches the old one (old becomes orphan -> cleanup)
- Listing: enforced max limits from config (`max_photos`, `max_videos`, `max_documents`)

### URL generation

Variant URLs in responses are presigned download URLs generated on-the-fly with configurable expiry. Bucket stays private — no public access needed.

---

## Cleanup Strategy

### Layer 1 — Immediate deletion (service layer)

When an entity is deleted, its media is cleaned up as part of the operation. S3 file deletion is enqueued as an ARQ job so API responses aren't blocked.

| Trigger | Action |
|---------|--------|
| Listing deleted | Query media by `owner_type=listing, owner_id=id` -> enqueue S3 delete jobs -> delete DB records |
| Organization deleted | **Before** deleting the org: query all org listings, clean up media for each listing + org profile photo, then delete org (Tortoise CASCADE handles listing DB records). Must happen pre-delete because CASCADE bypasses Python hooks. |
| User deleted (if supported) | Profile photo deleted |
| Profile photo replaced | Old photo's `owner_type`/`owner_id` set to null -> becomes orphan -> Layer 2 |
| Listing media updated | Removed media IDs get `owner_type`/`owner_id` set to null -> Layer 2 |

### Layer 2 — Orphan cleanup (ARQ cron job)

Runs every `orphan_cleanup_interval_minutes` (default: 60 min).

**Query:** `Media WHERE owner_type IS NULL AND created_at < now() - orphan_cleanup_after_hours`

For each match:
1. Delete all S3 files (`pending/{id}/...` and `media/{id}/...`)
2. Delete DB record

**Catches:**
- Uploads where user never submitted the form
- Media detached by entity updates where ARQ delete job failed
- Any edge case where immediate deletion was missed
- Media stuck in `pending_upload` (presigned URL issued but never used)

**Failed processing:** Media with `status=failed` is NOT auto-deleted; kept for manual inspection.

---

## Module Structure

```
app/media/
  __init__.py
  models.py          # Media model + enums
  schemas.py         # Pydantic request/response schemas
  router.py          # Upload URL, confirm, status, delete, retry endpoints
  service.py         # Business logic (attach, detach, validate, delete)
  storage.py         # S3-compatible storage client
  processing.py      # Image/video processing functions (Pillow, ffmpeg)
  worker.py          # ARQ worker definition, job handlers, cron functions
  dependencies.py    # Permission checking for media operations
```

---

## Architecture Decision: ARQ over Temporal

The processing pipeline is a simple linear job: download -> convert -> resize -> upload -> update DB. There are no sagas, multi-service coordination, or long-running workflows that would justify Temporal's infrastructure overhead (Temporal server + its own PostgreSQL + Elasticsearch).

ARQ provides reliable async job processing, retries with backoff, and built-in cron scheduling with just a Redis container (~6MB RAM). It's async-native Python, shares the same codebase (models, config, S3 client), and is a single deployment unit.
