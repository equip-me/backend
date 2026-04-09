# Listing Media Permission Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow org admins/editors to manage listing media (reorder, detach) regardless of who uploaded it.

**Architecture:** Remove the uploader ownership check from `attach_listing_media()` and propagate the signature change to callers. Update business-logic doc and tests.

**Tech Stack:** Python, FastAPI, Tortoise ORM, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/media/service.py` | Modify (lines 245-311) | Remove `user` param and uploader check from `attach_listing_media()` |
| `app/listings/service.py` | Modify (lines 103, 137) | Stop passing `user` to `attach_listing_media()`; remove `user` param from `update_listing()` |
| `app/listings/router.py` | Modify (line 46-50) | Stop extracting/passing `user` in `update_listing` route |
| `tests/db/test_media.py` | Modify (lines 1067-1091) | Update `test_attach_listing_media_wrong_uploader` to expect 201 |
| `docs/business-logic.md` | Modify (line 788) | Update permissions table |

---

### Task 1: Update `attach_listing_media()` — remove uploader check

**Files:**
- Modify: `app/media/service.py:245-311`

- [ ] **Step 1: Remove `user` parameter and uploader check**

Change the function signature and loop body. The full updated function:

```python
@traced
async def attach_listing_media(
    listing_id: str,
    photo_ids: list[UUID],
    video_ids: list[UUID],
    document_ids: list[UUID],
    storage: StorageClient,
) -> None:
    """Attach media to a listing. Detaches all current media first (removed ones become orphans)."""
    _ = storage  # reserved for future use
    settings = get_settings()

    if len(photo_ids) > settings.media.listing_limits_max_photos:
        raise AppValidationError(
            f"Maximum {settings.media.listing_limits_max_photos} photos allowed",
            code="media.limit_exceeded",
            params={"max": settings.media.listing_limits_max_photos, "kind": MediaKind.PHOTO.value},
        )
    if len(video_ids) > settings.media.listing_limits_max_videos:
        raise AppValidationError(
            f"Maximum {settings.media.listing_limits_max_videos} videos allowed",
            code="media.limit_exceeded",
            params={"max": settings.media.listing_limits_max_videos, "kind": MediaKind.VIDEO.value},
        )
    if len(document_ids) > settings.media.listing_limits_max_documents:
        raise AppValidationError(
            f"Maximum {settings.media.listing_limits_max_documents} documents allowed",
            code="media.limit_exceeded",
            params={"max": settings.media.listing_limits_max_documents, "kind": MediaKind.DOCUMENT.value},
        )

    # Detach all current media from this listing
    await Media.filter(
        owner_type=MediaOwnerType.LISTING,
        owner_id=listing_id,
    ).update(owner_type=None, owner_id=None)

    # Attach new media with position ordering
    all_ids_with_kind: list[tuple[UUID, MediaKind]] = [
        *[(pid, MediaKind.PHOTO) for pid in photo_ids],
        *[(vid, MediaKind.VIDEO) for vid in video_ids],
        *[(did, MediaKind.DOCUMENT) for did in document_ids],
    ]
    for position, (media_id, expected_kind) in enumerate(all_ids_with_kind):
        media = await Media.get_or_none(id=media_id)
        if media is None:
            raise NotFoundError(f"Media {media_id} not found", code="media.not_found")
        if media.status != MediaStatus.READY:
            raise AppValidationError(
                f"Media {media_id} is not ready",
                code="media.not_ready",
                params={"id": str(media_id)},
            )
        if media.kind != expected_kind:
            raise AppValidationError(
                f"Media {media_id} is {media.kind.value}, expected {expected_kind.value}",
                code="media.wrong_kind",
                params={"id": str(media_id), "kind": media.kind.value, "expected_kind": expected_kind.value},
            )

        media.owner_type = MediaOwnerType.LISTING
        media.owner_id = listing_id
        media.position = position
        await media.save()
```

Key changes vs current code:
- Removed `user: User` parameter
- Removed `.prefetch_related("uploaded_by")` from the query (line 289)
- Removed the `uploader` variable and the `uploader.id != user.id` check (lines 292-294)

- [ ] **Step 2: Run ruff and mypy**

```bash
task ruff:fix && task mypy
```

Expected: mypy will report errors in `app/listings/service.py` because callers still pass `user` — that's expected and fixed in Task 2.

- [ ] **Step 3: Commit**

```bash
git add app/media/service.py
git commit -m "fix(media): remove uploader check from attach_listing_media

Org editors/admins can now manage listing media regardless of who
uploaded it. The org editor permission on the route is sufficient."
```

---

### Task 2: Update callers in listings service and router

**Files:**
- Modify: `app/listings/service.py:103-166`
- Modify: `app/listings/router.py:40-50`

- [ ] **Step 1: Update `create_listing` call site**

In `app/listings/service.py`, change the `attach_listing_media` call inside `create_listing` (lines 122-130) from:

```python
    if data.photo_ids or data.video_ids or data.document_ids:
        await media_service.attach_listing_media(
            listing.id,
            data.photo_ids,
            data.video_ids,
            data.document_ids,
            user,
            storage,
        )
```

to:

```python
    if data.photo_ids or data.video_ids or data.document_ids:
        await media_service.attach_listing_media(
            listing.id,
            data.photo_ids,
            data.video_ids,
            data.document_ids,
            storage,
        )
```

- [ ] **Step 2: Update `update_listing` — remove `user` param and call site**

In `app/listings/service.py`, change the function signature (line 137-138) from:

```python
async def update_listing(
    listing: Listing, org: Organization, data: ListingUpdate, user: User, storage: StorageClient
) -> ListingRead:
```

to:

```python
async def update_listing(
    listing: Listing, org: Organization, data: ListingUpdate, storage: StorageClient
) -> ListingRead:
```

And change the `attach_listing_media` call (lines 157-164) from:

```python
    if has_media_update:
        await media_service.attach_listing_media(
            listing.id,
            data.photo_ids if data.photo_ids is not None else [],
            data.video_ids if data.video_ids is not None else [],
            data.document_ids if data.document_ids is not None else [],
            user,
            storage,
        )
```

to:

```python
    if has_media_update:
        await media_service.attach_listing_media(
            listing.id,
            data.photo_ids if data.photo_ids is not None else [],
            data.video_ids if data.video_ids is not None else [],
            data.document_ids if data.document_ids is not None else [],
            storage,
        )
```

- [ ] **Step 3: Update router `update_listing` call site**

In `app/listings/router.py`, change the `update_listing` handler (lines 40-50) from:

```python
@router.patch("/organizations/{org_id}/listings/{listing_id}", response_model=ListingRead)
async def update_listing(
    data: ListingUpdate,
    listing: Annotated[Listing, Depends(resolve_listing)],
    membership: Annotated[Membership, Depends(require_org_editor)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> ListingRead:
    await membership.fetch_related("organization", "user")
    org: Organization = membership.organization
    user: User = membership.user
    return await service.update_listing(listing, org, data, user, storage)
```

to:

```python
@router.patch("/organizations/{org_id}/listings/{listing_id}", response_model=ListingRead)
async def update_listing(
    data: ListingUpdate,
    listing: Annotated[Listing, Depends(resolve_listing)],
    membership: Annotated[Membership, Depends(require_org_editor)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> ListingRead:
    await membership.fetch_related("organization")
    org: Organization = membership.organization
    return await service.update_listing(listing, org, data, storage)
```

Note: removed `"user"` from `fetch_related`, removed `user` variable, removed `user` from the service call.

- [ ] **Step 4: Check if `User` import is still needed in `router.py`**

Check if `User` is used elsewhere in the file. If it's only used in the `update_listing` handler, remove the import.

- [ ] **Step 5: Run ruff, mypy, and tests**

```bash
task ruff:fix && task mypy && task test
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/media/service.py app/listings/service.py app/listings/router.py
git commit -m "fix(listings): propagate attach_listing_media signature change to callers"
```

---

### Task 3: Update test and docs

**Files:**
- Modify: `tests/db/test_media.py:1067-1091`
- Modify: `docs/business-logic.md:788`

- [ ] **Step 1: Update `test_attach_listing_media_wrong_uploader`**

In `tests/db/test_media.py`, rename and update the test (lines 1067-1091) from:

```python
async def test_attach_listing_media_wrong_uploader(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
    create_user: Any,
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    # Create a photo uploaded by a different user
    other_data, _ = await create_user(email="other-uploader@example.com", phone="+79009998877")
    photo_id = await _create_ready_photo(other_data["id"], "listing")

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/listings/",
        json={
            "name": "Wrong uploader test",
            "category_id": category_id,
            "price": 1000.00,
            "photo_ids": [str(photo_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
```

to:

```python
async def test_attach_listing_media_uploaded_by_other_org_member(
    client: AsyncClient,
    verified_org: tuple[dict[str, str], str],
    seed_categories: list[Any],
    create_user: Any,
) -> None:
    org_data, token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    # Create a photo uploaded by a different user — org editors can attach any media
    other_data, _ = await create_user(email="other-uploader@example.com", phone="+79009998877")
    photo_id = await _create_ready_photo(other_data["id"], "listing")

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/listings/",
        json={
            "name": "Other uploader test",
            "category_id": category_id,
            "price": 1000.00,
            "photo_ids": [str(photo_id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
```

- [ ] **Step 2: Update business-logic.md permissions table**

In `docs/business-logic.md`, change line 788 from:

```
| Attach to Listing | Uploader + Org Editor of the listing's organization |
```

to:

```
| Attach to Listing | Org Editor of the listing's organization |
```

- [ ] **Step 3: Run full test suite**

```bash
task test
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/db/test_media.py docs/business-logic.md
git commit -m "fix(media): update test and docs for listing media permission change"
```
