# Production Concurrency Upgrade Design

> Date: 2026-05-07
> Scope: upgrade the notification service architecture from local-first SQLite single-worker deployment to a server-ready design that can switch to Postgres and safely run multiple workers.

## Why this upgrade exists

The assignment emphasizes architecture design and system boundaries. The existing implementation proves the reliability loop, but it honestly documents that SQLite + one worker is not a high-concurrency architecture. Since the service has already been deployed to a server and time is available, the design should show the next production step without jumping straight to MQ.

## Design goal

Keep the local developer experience simple while making the production path explicit:

- Local/default: SQLite, one API process, one worker process.
- Server/concurrency path: Postgres, multiple API workers, multiple notification workers.
- Still no MQ in this step. MQ remains a later evolution when queue depth, throughput, or isolation needs prove it.

## Boundary statement

This upgrade changes the persistence and claiming model. It does not change delivery semantics, business boundaries, API request shape, or vendor responsibilities.

In scope:

- Environment-driven `DATABASE_URL`.
- SQLite remains default for local runs.
- Postgres dependency and documented deployment config.
- Postgres-safe job claiming with row-level locks and `SKIP LOCKED`.
- Documentation that explains concurrency limits and evolution.

Out of scope:

- Running a local Postgres service in tests.
- Adding RabbitMQ/Kafka.
- Adding admin UI, auth, metrics, tracing, or vendor-specific adapters.
- Claiming exactly-once delivery.

## Storage strategy

`DATABASE_URL` controls the database:

```text
SQLite:   sqlite:///./notification_service.db
Postgres: postgresql+psycopg://user:password@127.0.0.1:5432/notify_db
```

SQLAlchemy supports both through the same ORM models.

## Claim strategy

For SQLite, keep the existing simple select-then-update claim. It is fine for single-worker local/demo usage.

For Postgres, claim jobs using row-level locks:

```python
select(Notification)
  .where(status in ('pending', 'retrying'))
  .where(next_attempt_at <= now)
  .order_by(next_attempt_at, created_at)
  .limit(batch_size)
  .with_for_update(skip_locked=True)
```

This lets multiple worker processes safely claim different rows without blocking or duplicating work.

## Testing strategy

Unit tests do not require a live Postgres server. They verify:

- `Settings.from_env()` reads `DATABASE_URL` and defaults to SQLite.
- SQLite engine uses `check_same_thread=False`.
- Postgres engine does not use SQLite-only connect args.
- Repository builds a Postgres claim statement with `FOR UPDATE SKIP LOCKED` semantics.
- Existing notification flow tests still pass on SQLite.

## Interview framing

The correct answer is not "we made it infinitely scalable". The correct answer is:

> V1 uses SQLite to prove the reliability loop. The server-ready path switches the same codebase to Postgres through `DATABASE_URL`. Multiple workers are safe because Postgres claim uses row-level locking and `SKIP LOCKED`. MQ is intentionally not in this step because the next bottleneck is first durable storage and safe claim; MQ comes later when queue depth and operational isolation justify it.
