# Reliable HTTP Notification Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interview-ready reliable HTTP notification service with durable acceptance, asynchronous delivery, retry policy, attempt history, crash recovery, and strong documentation.

**Architecture:** FastAPI accepts notification intent and persists it to SQLite before delivery. A worker claims due jobs, dispatches HTTP requests, records attempts, applies a bounded retry policy, and recovers stale processing jobs. The design intentionally uses a database-backed queue for version 1 and documents how to evolve to Postgres/MQ later.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.x, SQLite, httpx, pytest.

---

## File map

- `src/app/config.py`: immutable runtime settings.
- `src/app/database.py`: SQLAlchemy engine/session helpers and schema initialization.
- `src/app/models.py`: persistence models, statuses, and HTTP method constants.
- `src/app/schemas.py`: FastAPI/Pydantic request and response contracts.
- `src/app/retry_policy.py`: pure retry classification and backoff decisions.
- `src/app/repository.py`: all database reads/writes for notifications and attempts.
- `src/app/dispatcher.py`: HTTP dispatch result normalization.
- `src/app/worker.py`: worker orchestration.
- `src/app/main.py`: FastAPI app factory and routes.
- `src/app/__init__.py`, `src/__init__.py`: package markers.
- `tests/conftest.py`: isolated test database/app fixtures.
- `tests/test_retry_policy.py`: TDD tests for delivery semantics.
- `tests/test_notification_flow.py`: TDD tests for API, worker, and crash recovery.
- `README.md`: primary interview-facing design and runbook.
- `AI_USAGE.md`: assignment-required AI usage explanation.
- `docs/architecture.md`: detailed architecture notes.
- `docs/api.md`: API contract.
- `docs/decisions.md`: ADR-style decision log.
- `requirements.txt`: dependencies.
- `.gitignore`: local artifacts.

## Task 1: Retry policy

**Files:**
- Create: `tests/test_retry_policy.py`
- Create: `src/app/retry_policy.py`

- [ ] Step 1: Write failing tests for retry decisions.

```python
from datetime import datetime, timezone

from src.app.retry_policy import DeliveryOutcome, RetryPolicy, classify_delivery


def test_2xx_response_succeeds_without_retry():
    outcome = classify_delivery(status_code=204, error=None, attempt_count=1, max_attempts=5)

    assert outcome.status == "succeeded"
    assert outcome.should_retry is False
    assert outcome.next_attempt_at is None


def test_transient_5xx_response_retries_with_exponential_backoff():
    now = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
    policy = RetryPolicy(base_delay_seconds=60, max_delay_seconds=3600)

    outcome = classify_delivery(
        status_code=503,
        error=None,
        attempt_count=3,
        max_attempts=5,
        now=now,
        policy=policy,
    )

    assert outcome.status == "retrying"
    assert outcome.should_retry is True
    assert outcome.next_attempt_at == datetime(2026, 5, 7, 10, 4, 0, tzinfo=timezone.utc)
    assert outcome.reason == "transient_http_status"


def test_network_error_retries_until_attempts_are_exhausted():
    now = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)

    outcome = classify_delivery(
        status_code=None,
        error="timeout",
        attempt_count=2,
        max_attempts=5,
        now=now,
        policy=RetryPolicy(base_delay_seconds=10, max_delay_seconds=60),
    )

    assert outcome.status == "retrying"
    assert outcome.should_retry is True
    assert outcome.next_attempt_at == datetime(2026, 5, 7, 10, 0, 20, tzinfo=timezone.utc)
    assert outcome.reason == "network_error"


def test_permanent_4xx_response_fails_without_retry():
    outcome = classify_delivery(status_code=400, error=None, attempt_count=1, max_attempts=5)

    assert outcome.status == "failed"
    assert outcome.should_retry is False
    assert outcome.next_attempt_at is None
    assert outcome.reason == "permanent_http_status"


def test_transient_error_fails_when_attempts_are_exhausted():
    outcome = classify_delivery(status_code=503, error=None, attempt_count=5, max_attempts=5)

    assert outcome.status == "failed"
    assert outcome.should_retry is False
    assert outcome.next_attempt_at is None
    assert outcome.reason == "attempts_exhausted"


def test_backoff_is_capped():
    now = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)

    outcome = classify_delivery(
        status_code=429,
        error=None,
        attempt_count=10,
        max_attempts=20,
        now=now,
        policy=RetryPolicy(base_delay_seconds=60, max_delay_seconds=300),
    )

    assert outcome.next_attempt_at == datetime(2026, 5, 7, 10, 5, 0, tzinfo=timezone.utc)
```

- [ ] Step 2: Run tests and verify failure.

Run: `python -m pytest tests/test_retry_policy.py -q`
Expected: import failure for missing `src.app.retry_policy`.

- [ ] Step 3: Implement retry policy.

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


TRANSIENT_STATUS_CODES = {408, 409, 425, 429}


@dataclass(frozen=True)
class RetryPolicy:
    base_delay_seconds: int = 60
    max_delay_seconds: int = 3600

    def delay_for_attempt(self, attempt_count: int) -> timedelta:
        exponent = max(attempt_count - 1, 0)
        seconds = self.base_delay_seconds * (2 ** exponent)
        return timedelta(seconds=min(seconds, self.max_delay_seconds))


@dataclass(frozen=True)
class DeliveryOutcome:
    status: str
    should_retry: bool
    next_attempt_at: datetime | None
    reason: str


def classify_delivery(
    *,
    status_code: int | None,
    error: str | None,
    attempt_count: int,
    max_attempts: int,
    now: datetime | None = None,
    policy: RetryPolicy | None = None,
) -> DeliveryOutcome:
    policy = policy or RetryPolicy()
    now = now or datetime.now(timezone.utc)

    if status_code is not None and 200 <= status_code < 300:
        return DeliveryOutcome("succeeded", False, None, "success")

    if attempt_count >= max_attempts:
        return DeliveryOutcome("failed", False, None, "attempts_exhausted")

    if error:
        return DeliveryOutcome("retrying", True, now + policy.delay_for_attempt(attempt_count), "network_error")

    if status_code is not None and (status_code >= 500 or status_code in TRANSIENT_STATUS_CODES):
        return DeliveryOutcome("retrying", True, now + policy.delay_for_attempt(attempt_count), "transient_http_status")

    return DeliveryOutcome("failed", False, None, "permanent_http_status")
```

- [ ] Step 4: Run tests and verify pass.

Run: `python -m pytest tests/test_retry_policy.py -q`
Expected: `6 passed`.

## Task 2: Persistence repository

**Files:**
- Create: `src/__init__.py`
- Create: `src/app/__init__.py`
- Create: `src/app/config.py`
- Create: `src/app/database.py`
- Create: `src/app/models.py`
- Create: `src/app/repository.py`
- Create: `tests/conftest.py`
- Create: `tests/test_notification_flow.py`

- [ ] Step 1: Write failing repository tests.

```python
from datetime import datetime, timedelta, timezone

from src.app.models import STATUS_PENDING, STATUS_PROCESSING, STATUS_RETRYING
from src.app.repository import NotificationRepository


def test_repository_creates_and_fetches_notification(session):
    repo = NotificationRepository(session)

    created = repo.create_notification(
        target_url="https://vendor.example.test/webhook",
        method="POST",
        headers={"Authorization": "Bearer token"},
        body={"event": "user_registered"},
        idempotency_key="user_registered:u_1",
        max_attempts=5,
    )

    fetched = repo.get_notification(created.id)

    assert fetched is not None
    assert fetched.status == STATUS_PENDING
    assert fetched.target_url == "https://vendor.example.test/webhook"
    assert fetched.headers == {"Authorization": "Bearer token"}
    assert fetched.body == {"event": "user_registered"}
    assert fetched.idempotency_key == "user_registered:u_1"


def test_repository_claims_due_jobs_and_marks_processing(session):
    repo = NotificationRepository(session)
    due = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
    job = repo.create_notification(
        target_url="https://vendor.example.test/webhook",
        method="POST",
        headers={},
        body={},
        idempotency_key=None,
        max_attempts=5,
        now=due - timedelta(minutes=1),
    )
    repo.schedule_retry(job.id, next_attempt_at=due - timedelta(seconds=1), error="temporary")

    claimed = repo.claim_due_notifications(limit=10, now=due)

    assert [item.id for item in claimed] == [job.id]
    fetched = repo.get_notification(job.id)
    assert fetched.status == STATUS_PROCESSING
    assert fetched.processing_started_at == due


def test_repository_records_attempts(session):
    repo = NotificationRepository(session)
    job = repo.create_notification(
        target_url="https://vendor.example.test/webhook",
        method="POST",
        headers={},
        body={},
        idempotency_key=None,
        max_attempts=5,
    )

    repo.record_attempt(job.id, attempt_no=1, status_code=503, error=None, duration_ms=12)
    repo.mark_succeeded(job.id, status_code=204)
    fetched = repo.get_notification(job.id)

    assert fetched.status == "succeeded"
    assert fetched.last_status_code == 204
    assert len(fetched.attempts) == 1
    assert fetched.attempts[0].status_code == 503


def test_repository_recovers_stale_processing_jobs(session):
    repo = NotificationRepository(session)
    now = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
    job = repo.create_notification(
        target_url="https://vendor.example.test/webhook",
        method="POST",
        headers={},
        body={},
        idempotency_key=None,
        max_attempts=5,
        now=now - timedelta(minutes=10),
    )
    repo.claim_due_notifications(limit=1, now=now - timedelta(minutes=10))

    recovered = repo.recover_stale_processing(stale_before=now - timedelta(minutes=5), now=now)

    assert recovered == 1
    fetched = repo.get_notification(job.id)
    assert fetched.status == STATUS_RETRYING
    assert fetched.next_attempt_at == now
```

- [ ] Step 2: Run tests and verify failure.

Run: `python -m pytest tests/test_notification_flow.py -q`
Expected: import failure for missing repository/model modules.

- [ ] Step 3: Implement config, database, models, repository, and test fixtures.

- [ ] Step 4: Run repository tests and verify pass.

Run: `python -m pytest tests/test_notification_flow.py -q`
Expected: repository tests pass.

## Task 3: Dispatcher and worker

**Files:**
- Create: `src/app/dispatcher.py`
- Create: `src/app/worker.py`
- Modify: `tests/test_notification_flow.py`

- [ ] Step 1: Add failing worker tests for success and retry.

- [ ] Step 2: Run tests and verify failure.

Run: `python -m pytest tests/test_notification_flow.py -q`
Expected: import failure for missing worker/dispatcher or assertion failure.

- [ ] Step 3: Implement dispatcher and worker.

- [ ] Step 4: Run tests and verify pass.

Run: `python -m pytest tests/test_notification_flow.py -q`
Expected: all notification flow tests pass.

## Task 4: FastAPI app

**Files:**
- Create: `src/app/schemas.py`
- Create: `src/app/main.py`
- Modify: `tests/test_notification_flow.py`

- [ ] Step 1: Add failing API tests for create and get status.

- [ ] Step 2: Run tests and verify failure.

Run: `python -m pytest tests/test_notification_flow.py -q`
Expected: missing `create_app` or route failures.

- [ ] Step 3: Implement schemas and FastAPI routes.

- [ ] Step 4: Run tests and verify pass.

Run: `python -m pytest tests/test_notification_flow.py -q`
Expected: all notification flow tests pass.

## Task 5: Documentation and runbook

**Files:**
- Create: `README.md`
- Create: `AI_USAGE.md`
- Create: `docs/architecture.md`
- Create: `docs/api.md`
- Create: `docs/decisions.md`
- Create: `requirements.txt`
- Create: `.gitignore`

- [ ] Step 1: Write README with problem framing, architecture, delivery semantics, failure handling, run commands, and evolution.
- [ ] Step 2: Write AI_USAGE with accepted/rejected AI suggestions and human decisions.
- [ ] Step 3: Write detailed docs.
- [ ] Step 4: Add dependencies and ignore rules.
- [ ] Step 5: Run final verification.

Run: `python -m pytest -q`
Expected: all tests pass.

## Self-review

- Spec coverage: plan covers acceptance API, persistence, retry policy, attempts, worker delivery, crash recovery, docs, and AI usage.
- Placeholder scan: implementation details for Task 2-4 are intentionally summarized here because the active session will TDD them directly; no requirement remains unassigned.
- Type consistency: statuses are string constants shared by model/repository/worker/API.
