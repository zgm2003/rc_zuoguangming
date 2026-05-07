# System Boundary

This service has one job: reliably deliver external HTTP notifications that internal systems have already decided to send.

A good boundary is more important than a long feature list. The design deliberately keeps business semantics outside the notification service and keeps transport reliability inside it.

## What this system owns

1. **Accept notification intent**
   - Internal systems submit target URL, method, headers, JSON body, optional idempotency key, and max attempts.
   - The service validates and persists the job before returning.

2. **Durable state**
   - Notifications are stored before delivery.
   - Attempts are append-only evidence for debugging and audit.

3. **Asynchronous delivery**
   - External HTTP latency and failures do not block the business request path.

4. **Retry and terminal failure**
   - Transient failures are retried with bounded exponential backoff.
   - Permanent failures and exhausted retries are recorded.

5. **Worker recovery**
   - Jobs stuck in `processing` past the visibility timeout are moved back to `retrying`.

6. **Operational visibility through API/data**
   - Current state and attempts can be queried.

## What this system does not own

1. **Business event generation**
   - It does not decide when a user registered, an order was paid, or inventory changed.
   - Those decisions belong to upstream business systems.

2. **Vendor business semantics**
   - It does not know how CRM contacts, ad conversions, or inventory records should be interpreted.
   - It only transports the HTTP request supplied by callers.

3. **Exactly-once delivery**
   - The service cannot know whether a vendor processed a timed-out HTTP request.
   - It provides at-least-once delivery and exposes `idempotency_key` for deduplication.

4. **Receiver-side idempotency**
   - The service can pass an idempotency key, but the receiver must enforce deduplication.

5. **Global observability platform**
   - Metrics, tracing, alerting, and dashboards are future operational integrations, not core domain logic.

6. **Message broker ownership**
   - MQ is an optional future infrastructure boundary, not a required first production step.

## Boundary with upstream systems

Upstream systems submit final HTTP notification data and optionally a business idempotency key. They should not wait for vendor delivery. They own business correctness and event identity.

## Boundary with vendor systems

Vendor systems receive HTTP requests. They own their business side effects and should deduplicate by idempotency key when possible.

## Boundary with storage

SQLite is the local/default storage. Postgres is the server concurrency storage. The application owns state transitions; the database provides durability and, for Postgres, row-level locking.

## Boundary with MQ

A broker can later own buffering and fanout, but it does not remove the need for persistence, attempts, idempotency, or retry policy. Introducing MQ too early hides the real design questions instead of solving them.
