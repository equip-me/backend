# Listing Media Permission Fix

## Problem

When an org admin/editor updates a listing's media (e.g. reorder photos), the backend rejects the request with `media.not_uploader` if the media was uploaded by a different org member. The `attach_listing_media()` function enforces `uploader.id != user.id` for every media item, but the listing update endpoint already gates access via `require_org_editor`.

## Decision

Remove the uploader ownership check from `attach_listing_media()`. The org editor permission on the route is sufficient authorization for listing media management.

The uploader check remains in all other contexts:
- `require_media_uploader` dependency (confirm, delete, retry)
- `attach_profile_photo` (user/org profile photos)

## Changes

### 1. `app/media/service.py` — `attach_listing_media()`

- Remove the `user` parameter.
- Remove the `uploader.id != user.id` check (lines 292-294) and the `prefetch_related("uploaded_by")` it depends on.

### 2. `app/listings/service.py` — callers

- `create_listing()` (line 123): stop passing `user` to `attach_listing_media()`.
- `update_listing()` (line 157): stop passing `user` to `attach_listing_media()`.

### 3. `docs/business-logic.md` — permissions table

Change "Attach to Listing" permission from "Uploader + Org Editor of the listing's organization" to "Org Editor of the listing's organization".

### 4. `tests/db/test_media.py` — `test_attach_listing_media_wrong_uploader`

This test (line 1067) asserts that attaching media from a different uploader returns 403. Update it to assert 201 — this is now allowed behavior.

### 5. `docs/superpowers/specs/2026-04-07-api-error-contract-design.md`

The error catalog documents `media.not_uploader` as applicable when "User acts on another's media". No change needed — the error still exists for non-listing contexts.
