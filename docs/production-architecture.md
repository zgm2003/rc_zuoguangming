# Production Architecture

## Current deployed shape

```text
Client / internal business system
        |
        v
https://notify.zgm2003.cn
        |
        v
Nginx reverse proxy
        |
        v
127.0.0.1:8000
        |
        v
FastAPI API process
        |
        v
Database

Worker process
        |
        v
Database claim + external HTTP delivery
```

The API and worker are separate long-running processes. That separation is intentional: accepting a notification and delivering it to a vendor have different latency and failure profiles.

## Local/default mode

```bash
DATABASE_URL=sqlite:///./notification_service.db
python -m uvicorn src.app.main:app --reload
python -m src.app.worker_runner
```

Use this mode for local review and simple deployment. It proves the reliability loop but should not be sold as high-concurrency.

## Server concurrency mode

```bash
DATABASE_URL=postgresql+psycopg://notify_user:password@127.0.0.1:5432/notify_db
python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8000 --workers 2
python -m src.app.worker_runner --poll-interval 1 --batch-size 20
python -m src.app.worker_runner --poll-interval 1 --batch-size 20
```

In this mode, multiple API workers can accept requests and multiple notification workers can claim due jobs.

## Why Postgres changes the concurrency story

SQLite uses coarse write locking and has no row-level `SKIP LOCKED` claim primitive. It is fine for single-worker local operation.

Postgres supports row-level locking. The repository uses `FOR UPDATE SKIP LOCKED` for Postgres claim statements. That means two worker processes can ask for due jobs at the same time and receive different unlocked rows rather than duplicating the same notification.

This does not mean worker count can grow without limit. Each worker still holds database locks while it marks claimed rows as `processing`, and overall throughput is constrained by batch size, transaction length, vendor HTTP timeout, and database write capacity. The safe scaling rule is to keep claim transactions short, tune `--batch-size` deliberately, and watch queue age before adding more workers.

## Why this still does not claim infinite scale

This is a server-ready concurrency step, not a global notification platform. Remaining bottlenecks include:

- vendor rate limits;
- HTTP timeout volume;
- database write throughput;
- attempt table growth;
- lack of metrics and alerting;
- lack of per-vendor circuit breakers.

Those are future architecture decisions, not reasons to pollute version 1 with every possible subsystem.

## When to introduce MQ

Introduce RabbitMQ/Kafka when at least one of these is true:

- queue depth grows faster than workers can drain;
- notification production and delivery must be operationally isolated;
- fanout/routing becomes complex;
- retry scheduling needs broker-native delayed queues;
- multiple services need to consume the same event stream.

Until then, Postgres-backed durable queueing is simpler and easier to reason about.
