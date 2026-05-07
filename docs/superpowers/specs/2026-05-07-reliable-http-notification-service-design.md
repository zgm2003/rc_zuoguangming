# Reliable HTTP Notification Service Design

> Date: 2026-05-07
> Context: AI Coding assignment - API notification system design and implementation
> Goal: build an interview-ready implementation that demonstrates clear boundaries, reliability semantics, and pragmatic trade-offs.

## 1. Problem framing

Internal business systems emit business events that must trigger HTTP(S) calls to external vendor APIs. Vendor APIs differ by URL, headers, and request body. The business systems do not need the vendor response inline; they need confidence that the notification intent is durably accepted and later delivered as reliably as practical.

The core design move is to separate **accepting notification intent** from **performing external delivery**. A synchronous forwarding service would leak vendor latency and outages into internal business flows. This service instead persists the notification first, returns quickly, and lets a worker deliver it asynchronously.

## 2. System boundary

### In scope

- Accept notification requests from internal systems.
- Persist notification jobs before delivery.
- Support target URL, HTTP method, headers, JSON body, optional idempotency key, and optional max attempts.
- Deliver jobs asynchronously through a worker/dispatcher.
- Record each delivery attempt.
- Retry transient failures with bounded exponential backoff.
- Mark permanent failures and exhausted retries explicitly.
- Expose job status and attempts for debugging.
- Recover jobs stuck in `processing` after worker crash or process death.

### Out of scope for version 1

- Vendor-specific business adapters. The service transports HTTP requests; it does not understand CRM, ad, or inventory semantics.
- Exactly-once delivery. HTTP timeouts make it impossible to know whether the vendor processed the request.
- Full administration UI. API and persisted attempts are enough for this assignment.
- Multi-tenant permission system. Internal auth can be added at the gateway or service mesh layer first.
- Distributed scheduling, Kafka, Kubernetes, or sharded workers. They add operational complexity before there is evidence they are needed.
- Arbitrary templating DSL. The caller sends the final URL, headers, and body.

## 3. Delivery semantics

The service provides **at-least-once delivery** after a notification is accepted.

This is the only honest first-version guarantee for HTTP delivery. If a request times out, the vendor may have processed it even though this service did not receive a response. Retrying can duplicate delivery. Therefore every notification carries an optional `idempotency_key`, and the documentation states that callers/vendors should treat that key as the business event identity.

## 4. Architecture

```text
Business System
   |
   | POST /notifications
   v
FastAPI API
   |
   | validate + persist first
   v
SQLite notifications / attempts
   |
   | claim due jobs
   v
Worker + Dispatcher
   |
   | HTTP request with timeout
   v
External Vendor API
```

Version 1 uses a relational table as a durable queue. That is deliberately boring. It keeps the design inspectable and testable while still proving the important reliability behavior: persist before delivery, retry later, and preserve attempt history.

## 5. Components

- `main.py`: FastAPI routes and app factory.
- `schemas.py`: request/response contracts.
- `models.py`: SQLAlchemy persistence models and status enum constants.
- `repository.py`: database operations, job creation, due-job claiming, attempt recording, crash recovery.
- `retry_policy.py`: pure retry decision logic; easy to test without HTTP or database.
- `dispatcher.py`: executes one HTTP request and normalizes the result.
- `worker.py`: orchestration loop that claims jobs, calls dispatcher, applies retry policy, and updates state.
- `config.py`: runtime configuration.
- `database.py`: engine/session creation and schema initialization.

## 6. Data model

`notifications` stores the latest state of each notification:

- `id`
- `target_url`
- `method`
- `headers_json`
- `body_json`
- `idempotency_key`
- `status`: `pending`, `processing`, `succeeded`, `retrying`, `failed`
- `attempt_count`
- `max_attempts`
- `next_attempt_at`
- `processing_started_at`
- `last_status_code`
- `last_error`
- `created_at`
- `updated_at`

`notification_attempts` stores append-only delivery evidence:

- `id`
- `notification_id`
- `attempt_no`
- `status_code`
- `error`
- `duration_ms`
- `created_at`

## 7. Failure handling

- 2xx: success, mark `succeeded`.
- 408, 409, 425, 429, and 5xx: retry if attempts remain.
- network errors and timeouts: retry if attempts remain.
- most 4xx: permanent failure, mark `failed`.
- exhausted attempts: mark `failed`.

Backoff schedule is exponential with a cap:

```text
base_delay_seconds * 2^(attempt_count - 1), capped by max_delay_seconds
```

The default configuration uses 5 max attempts, 60 seconds base delay, and 3600 seconds max delay.

## 8. Crash recovery

A worker may crash after claiming a job but before updating it. Claimed jobs enter `processing` with `processing_started_at`. On startup or periodically, jobs that stay in `processing` longer than the configured visibility timeout are moved back to `retrying` and become claimable again.

This is a database-queue version of a visibility timeout. It is not perfect, but it removes the ugly stuck-job edge case without adding a message broker.

## 9. API contract

### Create notification

`POST /notifications`

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

Response: `202 Accepted`

```json
{
  "id": "...",
  "status": "pending"
}
```

### Get status

`GET /notifications/{id}` returns current state and attempts.

## 10. Testing strategy

Unit tests cover pure retry policy decisions:

- 2xx succeeds.
- transient status codes retry.
- permanent 4xx fails.
- exhausted attempts fail.
- backoff is capped.

Integration-style tests cover repository and API flow:

- API persists a job and returns 202 without calling the vendor.
- worker marks successful delivery as succeeded.
- worker records failed attempts and schedules retry.
- stale processing jobs are recovered.

## 11. Trade-offs and AI suggestions rejected

Rejected as over-engineering for version 1:

- Kafka/RabbitMQ as the default queue. Useful later, not needed to prove the core model.
- Microservice split. A single service has one responsibility already.
- Exactly-once delivery. It is a false promise for external HTTP calls without shared transaction boundaries.
- Vendor template DSL. It creates a second product inside this product.
- Admin UI. It does not improve the core reliability path for this assignment.

## 12. Evolution path

If traffic or criticality grows:

1. Replace SQLite with Postgres for concurrency and operational durability.
2. Add row-level locking or broker-backed queue semantics.
3. Introduce Redis/RabbitMQ/Kafka only when throughput, fanout, or operational isolation requires it.
4. Add per-vendor rate limits and circuit breakers.
5. Add authentication, audit logs, metrics, tracing, and alerting.
6. Add manual replay tooling and a small admin UI for support teams.

The path is incremental. No version-1 API has to break.
