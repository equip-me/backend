# Chat Integration Guide

This guide covers everything a frontend developer (or AI agent) needs to integrate with the equipment-sharing chat backend. The chat system is order-scoped: every order has exactly one chat thread between the requester and the organization.

---

## 1. Authentication

### REST Requests

Include the JWT in every request as a Bearer token:

```
Authorization: Bearer {jwt}
```

### WebSocket Connection

Pass the JWT as a query parameter:

```
ws://host/api/v1/orders/{order_id}/chat/ws?token={jwt}
```

### Obtaining a Token

```http
POST /api/v1/users/token
Content-Type: application/json

{"username": "user@example.com", "password": "secret"}
```

```json
{"access_token": "eyJ...", "token_type": "bearer"}
```

The same token is used for both REST and WebSocket.

---

## 2. WebSocket Connection

### URL

```
ws://host/api/v1/orders/{order_id}/chat/ws?token={jwt}
```

### On Successful Connect

The server immediately sends a `connected` frame:

```json
{
  "type": "connected",
  "data": {
    "chat_status": "active"
  }
}
```

`chat_status` is either `"active"` or `"read_only"`. See [Chat States](#7-chat-states) for details.

### Close Codes

| Code | Meaning |
|------|---------|
| 4001 | Authentication failed (missing, expired, or invalid token) |
| 4003 | Not a participant in this order's chat |
| 4004 | Order not found |

Always handle these codes on the client and present an appropriate message to the user.

---

## 3. WebSocket Frames

### Client → Server

**Send a message:**

```json
{
  "type": "message",
  "text": "Hello, is this equipment available next week?",
  "media_ids": ["550e8400-e29b-41d4-a716-446655440000"]
}
```

- `text` — required unless `media_ids` is non-empty; max 4000 characters
- `media_ids` — optional list of previously uploaded and confirmed media UUIDs

**Typing indicator:**

```json
{
  "type": "typing",
  "is_typing": true
}
```

Send `is_typing: false` (or simply stop sending `true`) to cancel the indicator. Typing events are not persisted.

**Mark messages as read:**

```json
{
  "type": "read",
  "until_message_id": "550e8400-e29b-41d4-a716-446655440001"
}
```

Marks all messages up to and including `until_message_id` as read by the current user.

---

### Server → Client

**Connection confirmation:**

```json
{
  "type": "connected",
  "data": {
    "chat_status": "active"
  }
}
```

**Incoming message (from either party):**

```json
{
  "type": "message",
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "side": "requester",
    "name": "Иван Петров",
    "text": "Hello, is this equipment available next week?",
    "media": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440002",
        "kind": "photo",
        "urls": {
          "thumbnail": "https://cdn.example.com/thumb/abc.jpg",
          "large": "https://cdn.example.com/large/abc.jpg"
        },
        "original_filename": "photo.jpg",
        "content_type": "image/jpeg"
      }
    ],
    "created_at": "2026-04-01T12:00:00Z",
    "read_at": null
  }
}
```

- `side` — `"requester"` or `"organization"`; use this to decide which bubble side to render
- `name` — display name of the sender
- `media` — empty array if no attachments
- `read_at` — ISO 8601 timestamp when the other party read the message, or `null`

**Typing indicator from the other side:**

```json
{
  "type": "typing",
  "data": {
    "side": "organization",
    "is_typing": true
  }
}
```

**Read receipt from the other side:**

```json
{
  "type": "read",
  "data": {
    "side": "organization",
    "until_message_id": "550e8400-e29b-41d4-a716-446655440001"
  }
}
```

Update the UI to show read ticks on all messages up to and including `until_message_id`.

**Error from server:**

```json
{
  "type": "error",
  "data": {
    "code": "rate_limited",
    "detail": "Too many messages, slow down"
  }
}
```

See [Error Codes](#6-error-codes) for the full list.

---

## 4. REST Endpoints

REST endpoints are for loading history and checking status before or after a WebSocket session.

### Requester (user-side)

**Get message history:**

```
GET /api/v1/orders/{order_id}/chat/messages?cursor={cursor}&limit=20
Authorization: Bearer {jwt}
```

**Get chat status:**

```
GET /api/v1/orders/{order_id}/chat/status
Authorization: Bearer {jwt}
```

### Organization-side

**Get message history:**

```
GET /api/v1/organizations/{org_id}/orders/{order_id}/chat/messages?cursor={cursor}&limit=20
Authorization: Bearer {jwt}
```

**Get chat status:**

```
GET /api/v1/organizations/{org_id}/orders/{order_id}/chat/status
Authorization: Bearer {jwt}
```

### Response Shapes

**Message list (paginated, newest first):**

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "side": "requester",
      "name": "Иван Петров",
      "text": "Hello, is this equipment available next week?",
      "media": [],
      "created_at": "2026-04-01T12:00:00Z",
      "read_at": "2026-04-01T12:01:00Z"
    }
  ],
  "next_cursor": "eyJpZCI6IjU1MGU4NDAwIn0=",
  "has_more": true
}
```

Pass `next_cursor` as the `cursor` query parameter to fetch the previous page. When `has_more` is `false`, you have reached the beginning of the history.

**Chat status:**

```json
{
  "status": "active",
  "unread_count": 3
}
```

**Media attachment object** (appears inside message `media` array):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440002",
  "kind": "photo",
  "urls": {
    "thumbnail": "https://cdn.example.com/thumb/abc.jpg",
    "large": "https://cdn.example.com/large/abc.jpg"
  },
  "original_filename": "photo.jpg",
  "content_type": "image/jpeg"
}
```

`kind` is one of `"photo"`, `"video"`, or `"document"`. Documents only have a `"large"` URL (no thumbnail).

---

## 5. Media Attachment Flow

Attach files to messages in four steps before sending the WebSocket frame.

### Step 1 — Request an upload URL

```http
POST /api/v1/media/upload-url
Authorization: Bearer {jwt}
Content-Type: application/json

{
  "kind": "photo",
  "context": "chat",
  "filename": "photo.jpg",
  "content_type": "image/jpeg",
  "file_size": 1024000
}
```

Response:

```json
{
  "media_id": "550e8400-e29b-41d4-a716-446655440002",
  "upload_url": "https://storage.example.com/presigned?sig=abc"
}
```

### Step 2 — Upload the file

```http
PUT {upload_url}
Content-Type: image/jpeg

<binary file data>
```

The `Content-Type` must match what was specified in Step 1. No `Authorization` header is needed here — the URL is pre-signed.

### Step 3 — Confirm the upload

```http
POST /api/v1/media/{media_id}/confirm
Authorization: Bearer {jwt}
```

### Step 4 — Poll until ready

```http
GET /api/v1/media/{media_id}/status
Authorization: Bearer {jwt}
```

Response:

```json
{
  "status": "processing"
}
```

Poll until `status` equals `"ready"`. Typical processing time is under 2 seconds for photos. Recommended poll interval: 500 ms, timeout after 30 seconds.

### Step 5 — Include in WebSocket message

Once `status == "ready"`, send the message frame with the `media_id`:

```json
{
  "type": "message",
  "text": "Here is a photo of the damage",
  "media_ids": ["550e8400-e29b-41d4-a716-446655440002"]
}
```

You may attach multiple files by uploading each one independently and listing all `media_ids` in a single frame.

---

## 6. Error Codes

These appear in `{"type": "error", "data": {"code": "...", "detail": "..."}}` frames over WebSocket.

| Code | Meaning | Suggested action |
|------|---------|-----------------|
| `rate_limited` | Too many messages per minute | Back off and notify the user to slow down |
| `read_only` | Chat is in read-only mode | Disable the input; show a "chat closed" banner |
| `validation_error` | Message failed validation (empty text with no media, text too long, unknown media ID) | Show inline form error |
| `invalid_json` | Malformed JSON frame sent by client | Log and fix the serialization bug |

---

## 7. Chat States

Every chat is in one of two states, returned in the `connected` frame and the REST `/chat/status` endpoint.

### `active`

- Send messages (text and/or media)
- Send and receive typing indicators
- Send and receive read receipts

### `read_only`

- View the full message history
- Mark messages as read
- Cannot send new messages or typing indicators

The chat transitions to `read_only` when the order reaches a terminal state (completed, cancelled, etc.) and the post-order cooldown period has expired. Attempting to send a message in `read_only` mode results in a `read_only` error frame.

**UI recommendation:** When `chat_status` is `read_only`, disable the message input and display a notice such as "This conversation is closed."

---

## 8. Example Sequences

### 8.1 Basic Connect, Send, and Receive

This sequence shows a requester opening a chat, sending a message, and receiving the echo delivered back via WebSocket.

```
CLIENT                                SERVER
  |                                      |
  |--- WS connect ?token=eyJ... -------> |
  |                                      |
  |<-- {"type":"connected",              |
  |     "data":{"chat_status":"active"}} |
  |                                      |
  |--- {"type":"message",                |
  |     "text":"Is this available?",     |
  |     "media_ids":[]} --------------> |
  |                                      |
  |<-- {"type":"message",                |
  |     "data":{                         |
  |       "id":"aaa-111",                |
  |       "side":"requester",            |
  |       "name":"Иван Петров",          |
  |       "text":"Is this available?",   |
  |       "media":[],                    |
  |       "created_at":"2026-04-01T...", |
  |       "read_at":null}}               |
  |                                      |
```

The server broadcasts the saved message to all connected participants, including the sender. Render all incoming `message` frames regardless of `side`.

---

### 8.2 Two-Party Conversation with Read Receipts

Both the requester and an organization representative are connected simultaneously.

```
REQUESTER                            SERVER                          ORG REP
  |                                     |                               |
  |--- WS connect ------------------>   |                               |
  |<-- connected (active) -----------   |                               |
  |                                     |   <-- WS connect ------------ |
  |                                     |   --> connected (active) ----> |
  |                                     |                               |
  |--- {"type":"typing",                |                               |
  |     "is_typing":true} ----------->  |                               |
  |                                     |  --> {"type":"typing",        |
  |                                     |       "data":{"side":         |
  |                                     |        "requester",           |
  |                                     |        "is_typing":true}} --> |
  |                                     |                               |
  |--- {"type":"message",               |                               |
  |     "text":"Hello!"} ------------>  |                               |
  |                                     |                               |
  |<-- message (id="aaa-111") -------   |  --> message (id="aaa-111") > |
  |                                     |                               |
  |                                     |  <-- {"type":"read",          |
  |                                     |       "until_message_id":     |
  |                                     |        "aaa-111"} ----------- |
  |                                     |                               |
  |<-- {"type":"read",                  |                               |
  |     "data":{"side":"organization",  |                               |
  |      "until_message_id":"aaa-111"}} |                               |
  |                                     |                               |
```

Update the requester's "aaa-111" bubble to show a read tick when the `read` frame arrives.

---

### 8.3 Handling Read-Only State

An order has been completed. The requester opens the chat and attempts to send a message.

```
CLIENT                                SERVER
  |                                      |
  |--- WS connect ?token=eyJ... -------> |
  |                                      |
  |<-- {"type":"connected",              |
  |     "data":{"chat_status":           |
  |              "read_only"}}           |
  |                                      |
  |  [UI disables input field,           |
  |   shows "Conversation is closed"]    |
  |                                      |
  |--- {"type":"message",                |
  |     "text":"One more question..."} > |  (user bypassed UI)
  |                                      |
  |<-- {"type":"error",                  |
  |     "data":{"code":"read_only",      |
  |      "detail":"Chat is read-only"}}  |
  |                                      |
  |  [UI keeps input disabled,           |
  |   optionally shows toast error]      |
  |                                      |
```

Always check `chat_status` in the `connected` frame and enforce read-only in the UI immediately. The server-side guard is a safety net, not the primary enforcement layer.

---

## Quick Reference

| What | Where |
|------|-------|
| Get token | `POST /api/v1/users/token` |
| WebSocket URL | `ws://host/api/v1/orders/{order_id}/chat/ws?token={jwt}` |
| Load history (requester) | `GET /api/v1/orders/{order_id}/chat/messages` |
| Load history (org) | `GET /api/v1/organizations/{org_id}/orders/{order_id}/chat/messages` |
| Chat status (requester) | `GET /api/v1/orders/{order_id}/chat/status` |
| Chat status (org) | `GET /api/v1/organizations/{org_id}/orders/{order_id}/chat/status` |
| Upload media | `POST /api/v1/media/upload-url` → PUT → `POST /api/v1/media/{id}/confirm` → GET status |
