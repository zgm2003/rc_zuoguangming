# Decision Log

## ADR-001: Persist before dispatch

Decision: The API persists the notification before any external HTTP call.

Why: External vendors are slower and less reliable than the internal request path. Persisting first isolates business systems from vendor failures.

Consequence: API returns `202 Accepted`, not vendor result.

## ADR-002: At-least-once delivery

Decision: The system provides at-least-once delivery.

Why: HTTP timeout makes exact delivery state unknowable. Retrying can duplicate delivery; not retrying can lose delivery.

Consequence: Callers should provide `idempotency_key`, and vendors should deduplicate by business event.

## ADR-003: Database queue for version 1

Decision: Use SQLite tables as the durable queue for this assignment.

Why: It proves the reliability model without introducing operational dependencies.

Consequence: High-concurrency worker scaling is not the goal of version 1. Future versions can move to Postgres or MQ.

## ADR-004: Attempt table is append-only evidence

Decision: Record every dispatch attempt separately.

Why: Final state alone is not enough for debugging. Attempts answer what happened, when, how long it took, and what response/error was seen.

Consequence: Storage grows with retries. Retention can be added later.

## ADR-005: Permanent 4xx failures do not retry

Decision: Most 4xx responses mark the notification failed immediately.

Why: Repeating malformed or unauthorized requests will not fix the problem and may harm vendors.

Consequence: 408, 409, 425, and 429 are treated as transient exceptions because retrying them is reasonable.

## ADR-006: Environment-driven database selection

Decision: The service uses `DATABASE_URL` to select the database. SQLite remains the default for local review; Postgres is the server concurrency path.

Why: The assignment should remain easy to run locally, but the architecture should not pretend SQLite is a high-concurrency queue.

Consequence: Deployment can move to Postgres without changing the API contract or worker command shape.

## ADR-007: Postgres workers claim with SKIP LOCKED

Decision: When running against Postgres, due notification claims use row-level locking with `FOR UPDATE SKIP LOCKED`.

Why: Multiple worker processes must not claim the same notification. `SKIP LOCKED` lets workers take different due rows without blocking each other.

Consequence: Multi-worker delivery is a Postgres feature, not a SQLite feature.

## ADR-008: Do not introduce MQ before the storage claim problem is solved

Decision: RabbitMQ/Kafka remains a later evolution, not part of this upgrade.

Why: The next concrete server problem is safe concurrent claiming. Postgres solves that with less operational complexity than a broker.

Consequence: MQ can be introduced later when queue depth, fanout, or operational isolation proves the need.
