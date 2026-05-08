# API Contract

## POST /notifications

Creates a notification job. The service persists the job and returns `202 Accepted`. This response means the notification was accepted for delivery, not that the vendor already processed it.

### Request

```json
{
  "target_url": "https://vendor.example.com/webhook",
  "method": "POST",
  "headers": {
    "Authorization": "Bearer token",
    "Content-Type": "application/json"
  },
  "body": {
    "event": "user_registered",
    "user_id": "u_123"
  },
  "idempotency_key": "user_registered:u_123",
  "max_attempts": 5
}
```

### Fields

| Field | Required | Notes |
|---|---:|---|
| `target_url` | yes | HTTP(S) vendor endpoint |
| `method` | no | `POST`, `PUT`, `PATCH`, `DELETE`; default `POST` |
| `headers` | no | string-to-string headers |
| `body` | no | JSON object |
| `idempotency_key` | no | recommended business event identity |
| `max_attempts` | no | 1 to 20; default 5 |

### Response

```json
{
  "id": "a3b0...",
  "status": "pending"
}
```

## GET /notifications/{id}

Returns current job state and attempt history.

Sensitive response fields are redacted in this read API. The dispatch payload remains stored for delivery, but fields such as `Authorization`, `Cookie`, `X-API-Key`, `token`, `password`, and `secret` are returned as `<redacted>`.

### Response

```json
{
  "id": "a3b0...",
  "target_url": "https://vendor.example.com/webhook",
  "method": "POST",
  "headers": {
    "Authorization": "<redacted>"
  },
  "body": {
    "event": "user_registered"
  },
  "idempotency_key": "user_registered:u_123",
  "status": "retrying",
  "attempt_count": 1,
  "max_attempts": 5,
  "next_attempt_at": "2026-05-07T10:01:00Z",
  "processing_started_at": null,
  "last_status_code": 503,
  "last_error": "transient_http_status",
  "created_at": "2026-05-07T10:00:00Z",
  "updated_at": "2026-05-07T10:00:00Z",
  "attempts": [
    {
      "attempt_no": 1,
      "status_code": 503,
      "error": null,
      "duration_ms": 12,
      "created_at": "2026-05-07T10:00:00Z"
    }
  ]
}
```
