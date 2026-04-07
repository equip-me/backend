# API Error Contract & Error Code Catalog

Specification for structured error responses across the rental platform API. Provides a machine-readable error contract that enables frontend i18n, contextual error rendering, and graceful degradation.

## API Error Response Contract

### REST Errors (4xx, 5xx)

Every error response follows this shape:

```json
{
  "code": "domain.error_name",
  "detail": "Human-readable English fallback",
  "params": {}
}
```

| Field    | Type     | Required | Description                                                        |
| -------- | -------- | -------- | ------------------------------------------------------------------ |
| `code`   | `string` | always   | Machine-readable, dot-separated: `{domain}.{error}`               |
| `detail` | `string` | always   | English fallback message (for debugging / non-i18n clients)        |
| `params` | `object` | always   | Key-value pairs for i18n interpolation. Empty `{}` when no dynamic values |

### Validation Errors (422)

Keeps FastAPI's native validation but wrapped consistently:

```json
{
  "code": "validation.request_invalid",
  "detail": "Request validation failed",
  "params": {},
  "errors": [
    {
      "field": "body.email",
      "code": "validation.invalid_email",
      "detail": "value is not a valid email address",
      "params": {}
    },
    {
      "field": "body.password",
      "code": "validation.password_too_short",
      "detail": "Password must be at least 8 characters",
      "params": { "min_length": 8 }
    }
  ]
}
```

The `errors` array only appears on 422 responses. Each entry has:

| Field    | Type     | Description                                         |
| -------- | -------- | --------------------------------------------------- |
| `field`  | `string` | Dot-path to the invalid field (derived from Pydantic `loc`) |
| `code`   | `string` | Field-level error code                              |
| `detail` | `string` | English fallback for this specific field            |
| `params` | `object` | Interpolation values for this field's error         |

### WebSocket Error Frames

Error frames sent over WebSocket follow the same `code`/`detail`/`params` structure, wrapped in the existing frame format:

```json
{
  "type": "error",
  "data": {
    "code": "chat.rate_limited",
    "detail": "Rate limit exceeded",
    "params": { "limit": 30, "window_seconds": 60 }
  }
}
```

WebSocket close codes remain protocol-level (not part of the error code system):

| Close Code | Meaning                  |
| ---------- | ------------------------ |
| 4001       | Authentication failed    |
| 4003       | Not a chat participant   |
| 4004       | Order not found          |

---

## Error Code Catalog

### Domain: `auth`

| Code                       | Status | Params | Detail                              | When                                     |
| -------------------------- | ------ | ------ | ----------------------------------- | ---------------------------------------- |
| `auth.invalid_credentials` | 401    | —      | Could not validate credentials      | Invalid/expired JWT, user not found by token |
| `auth.incorrect_password`  | 401    | —      | Incorrect username or password      | Login with wrong email or password       |
| `auth.account_suspended`   | 403    | —      | Account suspended                   | Suspended user attempts any action       |

### Domain: `users`

| Code               | Status | Params | Detail                                  | When                                      |
| ------------------ | ------ | ------ | --------------------------------------- | ----------------------------------------- |
| `users.not_found`  | 404    | —      | User not found                          | User ID doesn't exist                     |
| `users.email_taken`| 409    | —      | User with this email already exists     | Register or update profile with existing email |

### Domain: `org`

| Code                          | Status | Params | Detail                                                    | When                                          |
| ----------------------------- | ------ | ------ | --------------------------------------------------------- | --------------------------------------------- |
| `org.not_found`               | 404    | —      | Organization not found                                    | Org ID doesn't exist                          |
| `org.inn_taken`               | 409    | —      | Organization with this INN already exists                 | Create org with duplicate INN                 |
| `org.not_verified`            | 403    | —      | Organization is not verified                              | Unverified org attempts restricted action     |
| `org.membership_required`     | 403    | —      | Organization membership required                          | Non-member accesses org resource              |
| `org.editor_required`         | 403    | —      | Organization editor access required                       | Viewer attempts editor action                 |
| `org.admin_required`          | 403    | —      | Organization admin access required                        | Non-admin attempts admin action               |
| `org.platform_admin_required` | 403    | —      | Platform admin access required                            | Non-admin accesses platform route             |
| `org.platform_owner_required` | 403    | —      | Platform owner access required                            | Non-owner accesses owner route                |
| `org.member_already_exists`   | 409    | —      | User already has a membership in this organization        | Invite/join when membership exists            |
| `org.membership_not_found`    | 404    | —      | Membership not found                                      | Approve/accept/change role on missing membership |
| `org.not_candidate`           | 400    | —      | Only candidates can be approved                           | Approve non-candidate membership              |
| `org.not_invited`             | 400    | —      | Only invitations can be accepted                          | Accept non-invitation membership              |
| `org.not_own_invitation`      | 403    | —      | You can only accept your own invitation                   | User accepts another user's invite            |
| `org.not_active_member`       | 400    | —      | Can only change role of active members                    | Change role of non-member                     |
| `org.last_admin`              | 400    | —      | Cannot remove the last admin                              | Remove/demote sole admin                      |
| `org.cannot_remove_member`    | 403    | —      | Only admins can remove other members                      | Non-admin tries to remove another member      |
| `org.payment_details_not_found`| 404   | —      | Payment details not found                                 | Org has no payment details                    |

### Domain: `listings`

| Code                        | Status | Params | Detail             | When                                            |
| --------------------------- | ------ | ------ | ------------------ | ----------------------------------------------- |
| `listings.not_found`        | 404    | —      | Listing not found  | Listing ID doesn't exist                        |
| `listings.access_denied`    | 403    | —      | Access denied      | View listing of unverified org as non-member    |
| `listings.category_not_found`| 404   | —      | Category not found | Category ID invalid or unverified & not owned   |

### Domain: `orders`

| Code                          | Status | Params                                   | Detail                                                      | When                                      |
| ----------------------------- | ------ | ---------------------------------------- | ----------------------------------------------------------- | ----------------------------------------- |
| `orders.not_found`            | 404    | —                                        | Order not found                                             | Order ID doesn't exist                    |
| `orders.listing_unavailable`  | 400    | —                                        | Listing is not available for ordering                       | Listing not in PUBLISHED status           |
| `orders.org_not_verified`     | 403    | —                                        | Organization is not verified                                | Order from unverified org                 |
| `orders.start_date_in_past`   | 400    | —                                        | requested_start_date cannot be in the past                  | Start date before today                   |
| `orders.no_offered_dates`     | 400    | —                                        | Cannot approve order without offered dates                  | Approve without setting dates             |
| `orders.invalid_transition`   | 400    | `{"action": "cancel", "status": "finished"}` | Cannot cancel order in status finished                 | Invalid state machine transition          |
| `orders.reservation_overlap`  | 400    | —                                        | Cannot approve: overlapping reservation exists for this listing | Date conflict with existing reservation |

### Domain: `media`

| Code                        | Status | Params                                                  | Detail                                                    | When                               |
| --------------------------- | ------ | ------------------------------------------------------- | --------------------------------------------------------- | ---------------------------------- |
| `media.not_found`           | 404    | —                                                       | Media not found                                           | Media ID doesn't exist             |
| `media.not_uploader`        | 403    | —                                                       | You can only manage your own uploads                      | User acts on another's media       |
| `media.invalid_content_type`| 400    | `{"content_type": "text/plain", "kind": "photo"}`       | Content type 'text/plain' is not allowed for photo        | Upload with wrong MIME type        |
| `media.file_too_large`      | 400    | `{"max_mb": 50, "kind": "video"}`                       | File size exceeds maximum of 50 MB for video              | Upload exceeds limit               |
| `media.invalid_filename`    | 400    | —                                                       | Invalid filename                                          | Malformed filename                 |
| `media.not_pending_upload`  | 400    | `{"status": "ready"}`                                   | Media is in 'ready' state, expected 'pending_upload'      | Confirm already-processed media    |
| `media.upload_missing`      | 404    | —                                                       | Uploaded file not found in storage                        | File not in S3 after confirm       |
| `media.not_failed`          | 400    | —                                                       | Only failed media can be retried                          | Retry non-failed media             |
| `media.limit_exceeded`      | 400    | `{"max": 10, "kind": "photo"}`                          | Maximum 10 photo allowed                                  | Too many media attached            |
| `media.wrong_kind`          | 400    | `{"id": "abc", "kind": "video", "expected_kind": "photo"}` | Media abc is video, expected photo                    | Wrong media type for context       |
| `media.not_ready`           | 400    | `{"id": "abc"}`                                         | Media abc is not ready                                    | Attach non-ready media             |

### Domain: `chat`

REST errors (standard HTTP responses):

| Code                       | Status | Params | Detail                   | When                          |
| -------------------------- | ------ | ------ | ------------------------ | ----------------------------- |
| `chat.not_participant`     | 403    | —      | Not a chat participant   | Non-participant accesses chat |

WebSocket error frames (sent over open connection, do not close it):

| Code                       | Params                                 | Detail                                | When                              |
| -------------------------- | -------------------------------------- | ------------------------------------- | --------------------------------- |
| `chat.read_only`           | —                                      | Chat is in read-only mode             | Send message after cooldown       |
| `chat.rate_limited`        | `{"limit": 30, "window_seconds": 60}` | Rate limit exceeded                   | Too many messages                 |
| `chat.invalid_json`        | —                                      | Invalid JSON                          | Malformed WebSocket frame         |
| `chat.message_empty`       | —                                      | Message must have text or attachments | Empty message                     |
| `chat.message_too_long`    | `{"max_length": 4000}`                | Message exceeds maximum length        | Text too long                     |
| `chat.too_many_attachments`| `{"max": 10}`                          | Maximum 10 attachments per message    | Too many files in message         |
| `chat.invalid_media_id`    | `{"id": "..."}`                        | Invalid media ID                      | Non-UUID media reference          |
| `chat.media_not_found`     | `{"id": "..."}`                        | Media not found                       | Referenced media doesn't exist    |
| `chat.media_not_ready`     | `{"id": "..."}`                        | Media is not ready                    | Referenced media still processing |
| `chat.media_not_yours`     | `{"id": "..."}`                        | Media was not uploaded by you         | Attach another user's media       |

### Domain: `validation` (422 field-level)

| Code                              | Params                  | Detail                                       | When                     |
| --------------------------------- | ----------------------- | -------------------------------------------- | ------------------------ |
| `validation.request_invalid`      | —                       | Request validation failed                    | Top-level 422 wrapper    |
| `validation.required`             | —                       | Field required                               | Missing required field   |
| `validation.invalid_email`        | —                       | Value is not a valid email address            | Bad email format         |
| `validation.password_too_short`   | `{"min_length": 8}`     | Password must be at least 8 characters       | Short password           |
| `validation.password_no_lowercase`| —                       | Password must contain a lowercase letter     | Missing lowercase        |
| `validation.password_no_uppercase`| —                       | Password must contain an uppercase letter    | Missing uppercase        |
| `validation.password_no_digit`    | —                       | Password must contain a digit                | Missing digit            |
| `validation.invalid_phone`        | —                       | Invalid phone number format                  | Bad phone format         |
| `validation.invalid_type`         | `{"expected": "string"}`| Invalid type                                 | Wrong field type         |

### Domain: `server`

| Code                                  | Status | Params                    | Detail                              | When                              |
| ------------------------------------- | ------ | ------------------------- | ----------------------------------- | --------------------------------- |
| `server.internal_error`               | 500    | —                         | Internal server error               | Unhandled exception / ID gen fail |
| `server.external_service_unavailable` | 502    | `{"service": "dadata"}`   | Dadata service unavailable          | External API failure              |
| `server.external_service_not_found`   | 502    | `{"service": "dadata"}`   | Organization not found by INN       | External lookup returned nothing  |
