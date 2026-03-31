# Order Chat Design

Real-time messaging between renter and organization within an order context.

## Overview

Each order implicitly has a chat. No separate chat entity — the order is the chat room. Messages are exchanged between two sides: **requester** (the user who placed the order) and **organization** (any editor+ member of the order's org). The chat is created with the order and remains writable for a configurable cooldown period after the order reaches a terminal state.

## Data Model

### ChatMessage

| Field | Type | Details |
|-------|------|---------|
| id | UUID | PK (internal model) |
| order | FK -> Order | Required, `related_name="messages"` |
| sender | FK -> User | Actual user who sent the message |
| text | TextField | Nullable (attachment-only messages allowed) |
| created_at | DatetimeField | `auto_now_add=True` |
| read_at | DatetimeField | Nullable, set when the other side reads the message |

Constraints (validated at service layer, not DB):
- At least one of `text` or attachments must be present
- Max text length: 4000 characters
- Max attachments per message: 10

### Media integration

Reuses the existing media system with new enum values:
- `MediaOwnerType.MESSAGE` — `owner_id` points to `ChatMessage.id` (UUID as string)
- `MediaContext.CHAT`

Media is uploaded via the existing presigned URL flow, then linked to a message by passing `media_ids` in the WebSocket message frame.

### Chat-specific media variants

| Kind | Variants | Details |
|------|----------|---------|
| Photo | `thumbnail` (100x100), `large` (1200x900) | WebP conversion |
| Video | `original` (full size) | WebM transcode (VP9 + Opus), no resize |
| Document | none | Store original, no processing |

Configuration in `base.yaml` under `media.chat_variants`.

## Chat Lifecycle

### Active (read-write)

- Order is in a non-terminal status (`pending`, `offered`, `confirmed`, `active`), OR
- Order is in a terminal status AND `last_message.created_at + cooldown > now`

### Read-only

- Order is in a terminal status AND `last_message.created_at + cooldown <= now`
- If no messages were ever sent, cooldown starts from `order.updated_at` (terminal transition timestamp)

Terminal statuses: `finished`, `rejected`, `declined`, `canceled_by_user`, `canceled_by_organization`.

## Access Control

| Action | Requester | Org Editor+ | Org Viewer | Others |
|--------|-----------|-------------|------------|--------|
| Connect WebSocket | Yes | Yes | No | No |
| Send message | Yes (if active) | Yes (if active) | No | No |
| Read history (REST) | Yes | Yes | No | No |
| Typing indicator | Yes (if active) | Yes (if active) | No | No |
| Mark as read | Yes | Yes | No | No |

Authorization: a `require_chat_participant` dependency checks the user is either the order requester or an org editor+ for the order's organization.

## Message Authorship

- **DB:** `sender` FK always stores the actual user
- **API response:** author presented by side:
  - Requester's message -> `{"side": "requester", "name": "Иван Петров"}` (user full name)
  - Org member's message -> `{"side": "organization", "name": "ООО Ромашка"}` (org short name)

Individual org member identity is not exposed to the requester.

## WebSocket Protocol

### Connection

```
ws://host/api/v1/orders/{order_id}/chat/ws?token={jwt_token}
```

Auth via query param. On connect: validate JWT, check participant access, subscribe to Redis channel `chat:{order_id}`, send connection confirmation.

### Client -> Server frames

```jsonc
// Send message
{"type": "message", "text": "Hello", "media_ids": ["uuid1", "uuid2"]}

// Typing indicator
{"type": "typing", "is_typing": true}

// Mark messages as read (all messages up to this ID)
{"type": "read", "until_message_id": "uuid"}
```

### Server -> Client frames

```jsonc
// Connection confirmed
{"type": "connected", "data": {"chat_status": "active" | "read_only"}}

// New message
{"type": "message", "data": {"id": "uuid", "side": "requester" | "organization", "name": "...", "text": "Hello", "media": [...], "created_at": "..."}}

// Typing indicator
{"type": "typing", "data": {"side": "requester" | "organization", "is_typing": true}}

// Read receipt
{"type": "read", "data": {"side": "requester" | "organization", "until_message_id": "uuid"}}

// Error
{"type": "error", "data": {"code": "rate_limited" | "read_only" | "validation_error", "detail": "..."}}
```

### Behavior

- **Message flow:** validate -> persist to DB -> publish to Redis `chat:{order_id}` -> all connected clients receive (including sender for confirmation)
- **Typing:** ephemeral, not persisted, broadcast via Redis to other participants only
- **Read receipts:** persisted (`read_at` updated on messages up to `until_message_id` where sender != current user), broadcast via Redis
- **Rate limiting:** in-memory per-connection counter, 30 messages/minute, resets every 60 seconds. Exceeding returns error frame.
- **Read-only chat:** `connected` frame indicates status. `message`/`typing` frames return error. `read` frames still work.
- **Immutable messages:** no editing, no deletion.

## REST API Endpoints

### User-side (requester)

```
GET /api/v1/orders/{order_id}/chat/messages?cursor=...&limit=20
GET /api/v1/orders/{order_id}/chat/status
```

### Org-side

```
GET /api/v1/organizations/{org_id}/orders/{order_id}/chat/messages?cursor=...&limit=20
GET /api/v1/organizations/{org_id}/orders/{order_id}/chat/status
```

### Response shapes

**Messages:** paginated (cursor-based, newest first). Each message: `id`, `side`, `name`, `text`, `media`, `created_at`, `read_at`.

**Status:** `{"status": "active" | "read_only", "unread_count": 3}`.

### No REST write endpoint

Sending messages happens exclusively via WebSocket to keep a single write path.

## Redis Pub/Sub & Offline Notification

### Pub/Sub

- Channel per order: `chat:{order_id}`
- Published payloads: serialized JSON of server->client frames
- On WebSocket connect: subscribe. On disconnect: unsubscribe.
- Dedicated `redis.asyncio` client for pub/sub (separate from ARQ's job queue pool), configured via existing `worker.redis_url`.

### Connection registry (per-process)

```python
active_connections: dict[str, set[tuple[str, WebSocket]]]  # order_id -> (user_id, ws)
```

Used for delivering Redis messages to local sockets and avoiding echo on typing indicators.

### Offline notification

On every new message, enqueue ARQ job `notify_new_chat_message(order_id, message_id)`. The job is a stub — logs the event and provides a hook point for future push notifications. The job can check if the message was read within a grace period before dispatching.

## Configuration

Added to `base.yaml`:

```yaml
chat:
  cooldown_days: 7
  max_message_length: 4000
  max_attachments_per_message: 10
  rate_limit_per_minute: 30

media:
  chat_variants:
    photo:
      thumbnail: { max_width: 100, max_height: 100, format: webp }
      large: { max_width: 1200, max_height: 900, format: webp }
    video:
      original: { format: webm, video_codec: vp9, audio_codec: opus }
    document: null
```

## Testing Strategy

### Unit tests
- Chat liveness logic (active/read-only based on order status + cooldown + last message time)
- Message validation (text length, empty message rejection, attachment count)
- Rate limiting logic
- Side/name resolution (requester full name vs org short name)

### DB tests
- ChatMessage CRUD, ordering, read_at updates
- Cascade behavior (order deleted -> messages deleted)
- Media linking to messages

### Integration (E2E) tests
- WebSocket auth: valid token connects, invalid rejected, non-participant rejected
- Message flow: send via WebSocket -> persisted in DB -> delivered to other connected client
- Read receipts: mark read -> `read_at` updated -> receipt broadcast
- Typing indicators: sent and received, not persisted
- Chat lifecycle: active order send works; terminal within cooldown send works; terminal past cooldown read-only
- Rate limiting: exceed 30/min -> error frame
- Attachments: upload media -> send message with media_ids -> message includes media
- REST endpoints: message history pagination, chat status with unread count
- Offline notification: no active connections -> ARQ job enqueued

### Test utilities
- `create_order_with_chat()` fixture
- WebSocket test client helper wrapping starlette test WebSocket support
