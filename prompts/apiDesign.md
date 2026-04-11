# API Design

Design HTTP/REST or WebSocket APIs that are intuitive, consistent, and hard to misuse.

---

## Core Principles

1. **Predictable URLs.** Resources are nouns, not verbs. `GET /users` not `GET getUsers`.
2. **Idempotency for mutations.** `POST` creates, `PUT` replaces, `PATCH` updates. Idempotency keys on writes.
3. **Consistent error shapes.** Every error has: `code`, `message`, and a machine-readable `type`.
4. **Auth is explicit.** No endpoint assumes the caller is authenticated. State it.
5. **Version from day one.** `Accept: application/vnd.myapi+v1+json` or `/v1/` in path.

---

## Request/Response Shape

### Success

```json
{
  "ok": true,
  "payload": { ... }
}
```

### Error

```json
{
  "ok": false,
  "error": {
    "code": 4001,
    "message": "Human-readable description",
    "type": "validation_error"
  }
}
```

Error codes:
- 4xxx = client error (bad input, not authenticated, not found)
- 5xxx = server error (broke, not the caller's fault)

### Pagination

```json
{
  "ok": true,
  "payload": {
    "items": [...],
    "cursor": "opaque-string",
    "hasMore": true
  }
}
```

Use cursor-based pagination, not offset/page. Offset breaks on inserts.

---

## REST Checklist

- [ ] `GET /resources` — list, supports `?cursor=` pagination
- [ ] `GET /resources/:id` — single resource, 404 if not found
- [ ] `POST /resources` — create, returns 201 + `Location:` header
- [ ] `PUT /resources/:id` — replace (full), returns 200 or 404
- [ ] `PATCH /resources/:id` — partial update, returns 200 or 404
- [ ] `DELETE /resources/:id` — delete, returns 204 or 404
- [ ] `POST /resources/:id/actions/:verb` — for side-effect-only operations

---

## WebSocket Specific

### Message envelope (client → server)

```json
{
  "type": "req",
  "id": "unique-id",
  "method": "resource.method",
  "params": { ... }
}
```

### Message envelope (server → client)

```json
{
  "type": "res",
  "id": "unique-id",
  "ok": true,
  "payload": { ... }
}
```

### Events (server → client, no ID)

```json
{
  "type": "event",
  "event": "resource.changed",
  "payload": { ... }
}
```

---

## Auth Patterns

| Auth method | When to use |
|------------|-------------|
| Bearer token (JWT) | Stateless, short-lived tokens |
| API key | Server-to-server, long-lived |
| Signed requests | When tokens can't be stored client-side |
| Challenge/response | For device auth, password replacement |

Never put secrets in URL query params — they end up in logs.

---

## Versioning Rules

- Add fields only (never remove, never rename) — add new fields for breaking changes
- Deprecate with `X-Warning` header and `warning` field in response
- Sunset old versions after a window (e.g., 6 months)
- `Accept` header versioning: `Accept: application/vnd.api+json;version=2`

---

## Activation

Proceed with designing an API for: [describe the resource or system]
