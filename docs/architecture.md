# Architecture Notes

## Design principle

The service separates notification acceptance from external delivery. The API path is short and deterministic: validate input, persist the notification, return `202 Accepted`. The unreliable part - vendor HTTP delivery - happens in the worker path.

## State machine

```text
pending
  -> processing
    -> succeeded
    -> retrying
    -> failed

retrying
  -> processing
    -> succeeded
    -> retrying
    -> failed

processing
  -> retrying   # when stale processing recovery runs
```

## Why this state model is small

There is no separate `dead` state. In version 1, `failed` means either permanent failure or retries exhausted. Attempts carry the evidence needed to distinguish the cause. If operations later need separate manual replay queues, `failed` can be split into `failed` and `dead_lettered` without breaking the create API.

## Worker claim model

The repository claims due jobs by selecting `pending`/`retrying` rows whose `next_attempt_at <= now`, then moves them to `processing` and records `processing_started_at`.

SQLite is not ideal for high-concurrency claiming. That is acceptable for version 1. If concurrency grows, move to Postgres and use `SELECT ... FOR UPDATE SKIP LOCKED`, or move the queue to RabbitMQ/Kafka.

## Crash recovery

A worker can crash after claiming a row. The recovery method moves jobs stuck in `processing` longer than the visibility timeout back to `retrying`.

This is the database-backed equivalent of a queue visibility timeout.

## Worker process

Run the API and worker as two separate processes:

```bash
python -m uvicorn src.app.main:app --reload
python -m src.app.worker_runner
```

The runner initializes the database, periodically recovers stale `processing` jobs, then calls `NotificationWorker.run_once()` in a loop. `Ctrl+C` sets a stop event and exits cleanly after the current iteration.

## Idempotency

The system can include `Idempotency-Key` when dispatching if the caller provided `idempotency_key` and did not already set that header. This does not magically guarantee idempotency. It gives downstream systems a stable business event key to use.

## Scaling path

1. Replace SQLite with Postgres.
2. Add row-level locking for concurrent workers.
3. Add per-vendor rate limits.
4. Add circuit breakers for repeatedly failing vendors.
5. Add metrics and alerts around retry volume, failure rate, and job age.
6. Add manual replay tooling.
7. Introduce MQ when queue depth, throughput, or operational isolation proves the need.
