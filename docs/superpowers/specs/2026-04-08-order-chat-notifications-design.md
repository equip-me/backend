# Order Chat Notifications

System-generated notification messages in order chat. Both sides (requester and organization) receive special messages when order status changes. The frontend renders these with distinct visual treatment (color accent, etc.).

## Data Model

### New Enums

```python
class ChatMessageType(StrEnum):
    USER = "user"
    NOTIFICATION = "notification"

class NotificationType(StrEnum):
    STATUS_CHANGED = "status_changed"

class ChatSide(StrEnum):
    REQUESTER = "requester"
    ORGANIZATION = "organization"
```

### New Fields on `ChatMessage`

| Field | Type | Default | Nullable | Notes |
|-------|------|---------|----------|-------|
| `message_type` | `CharField(enum)` | `"user"` | No | Discriminator |
| `notification_type` | `CharField(enum)` | — | Yes | `null` for user messages |
| `recipient_side` | `CharField(enum)` | — | Yes | `null` for user messages (visible to both) |
| `notification_body` | `JSONField` | — | Yes | `null` for user messages |

### Existing Fields Changes

- `sender` FK — must become **nullable** (currently non-nullable). Migration required. `null` for notification messages.
- `text` — `null`
- `media` — `[]` (empty)
- `read_at` — `null` until recipient reads it

### `notification_body` Shape for `status_changed`

```json
{"old_status": "accepted", "new_status": "confirmed"}
```

## Notification Creation

Trigger point: `_record_transition()` in `app/orders/service.py`. For each status transition, create two `ChatMessage` rows — one per side.

```python
for side in (ChatSide.REQUESTER, ChatSide.ORGANIZATION):
    ChatMessage.create(
        order=order,
        sender=None,
        message_type="notification",
        notification_type="status_changed",
        recipient_side=side,
        notification_body={"old_status": old_status, "new_status": new_status},
        text=None,
        media=[],
    )
```

All transitions generate notifications, including automated ones (activate, finish, expire) — they already go through `_record_transition()`.

`_record_transition` must become `async` and receive the `order` reference. All callers are already async.

## Query Filtering & Pagination

Add a side-aware condition to `get_messages()` so each caller only sees their own notifications plus all regular messages:

```sql
WHERE order_id = :order_id
  AND (recipient_side IS NULL OR recipient_side = :side)
```

The caller's side is already known from the dependency layer (separate router paths for requester vs org). Pass `side` into `get_messages()`.

Unread count in `get_chat_status()` uses the same filter.

## WebSocket Broadcast

### Connection Registry Change

Store side in the connection registry. Currently stores `(user_id, websocket)` per order. Change to `(user_id, side, websocket)`. The side is resolved in the WebSocket dependency layer at connection time.

### Broadcast Logic

After creating the two notification rows, broadcast each only to connections matching the recipient side. Publish over Redis pub/sub as today, but include `recipient_side` in the payload so cross-worker fan-out filters correctly.

### WebSocket Message Format

```json
{
    "type": "notification",
    "payload": {
        "id": "uuid",
        "message_type": "notification",
        "notification_type": "status_changed",
        "notification_body": {"old_status": "accepted", "new_status": "confirmed"},
        "created_at": "2026-04-08T12:00:00Z",
        "read_at": null
    }
}
```

## API Schema Changes

`MessageRead` adds new fields:

```python
class MessageRead(BaseModel):
    id: UUID
    side: str                                    # "requester" or "organization"
    name: str | None                             # null for notifications
    text: str | None
    media: list[MediaAttachmentRead]
    message_type: ChatMessageType                # "user" or "notification"
    notification_type: NotificationType | None   # "status_changed" or null
    notification_body: dict[str, str] | None     # {"old_status": "...", "new_status": "..."} or null
    created_at: datetime
    read_at: datetime | None
```

`name` becomes nullable — notification messages have no sender.

For notifications, `side` reflects the `recipient_side`. For user messages, it reflects the sender's side (unchanged).

## Read Tracking

No changes to the read mechanism itself. The existing `mark_as_read` function sets `read_at` on unread messages for the order. The only adjustment is applying the side filter (`recipient_side IS NULL OR recipient_side = :side`) so it only marks the caller's notification rows as read.

Each side has their own notification row, so read state is independent.

## Testing

### DB Tests

- Create notification messages for both sides, verify each side only sees their own via `get_messages()`
- Verify unread count includes notifications only for the caller's side
- Verify `mark_as_read` only affects the caller's side notifications

### Integration Tests

- Trigger an order status transition, verify two `ChatMessage` rows created with correct fields
- GET messages endpoint: requester sees their notification, org sees theirs, neither sees the other's
- Chat status endpoint: unread count reflects notifications for the correct side

### WebSocket Tests

- Connect as requester + org member, trigger transition, verify each receives only their notification
- Verify notification message format matches the schema

### Edge Cases

- Notification created for terminal status (e.g., canceled) — chat still active during cooldown, notification delivered
- Read tracking: mark read as requester, verify org's notification still unread
