from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from src.app.dispatcher import DispatchResult
from src.app.main import create_app
from src.app.models import STATUS_FAILED, STATUS_PENDING, STATUS_PROCESSING, STATUS_RETRYING
from src.app.repository import NotificationRepository
from src.app.worker import NotificationWorker


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


class FakeDispatcher:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def dispatch(self, notification):
        self.calls.append(notification.id)
        return self.results.pop(0)


def test_worker_marks_successful_delivery_as_succeeded(session):
    repo = NotificationRepository(session)
    now = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
    job = repo.create_notification(
        target_url="https://vendor.example.test/webhook",
        method="POST",
        headers={},
        body={"event": "paid"},
        idempotency_key="paid:o_1",
        max_attempts=5,
        now=now - timedelta(minutes=1),
    )
    worker = NotificationWorker(
        repo,
        dispatcher=FakeDispatcher([DispatchResult(status_code=204, error=None, duration_ms=31)]),
    )

    processed = worker.run_once(now=now)

    fetched = repo.get_notification(job.id)
    assert processed == 1
    assert fetched.status == "succeeded"
    assert fetched.attempt_count == 1
    assert fetched.last_status_code == 204
    assert len(fetched.attempts) == 1
    assert fetched.attempts[0].duration_ms == 31


def test_worker_schedules_retry_for_transient_failure(session):
    repo = NotificationRepository(session)
    now = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
    job = repo.create_notification(
        target_url="https://vendor.example.test/webhook",
        method="POST",
        headers={},
        body={},
        idempotency_key=None,
        max_attempts=5,
        now=now - timedelta(minutes=1),
    )
    worker = NotificationWorker(
        repo,
        dispatcher=FakeDispatcher([DispatchResult(status_code=503, error=None, duration_ms=10)]),
    )

    worker.run_once(now=now)

    fetched = repo.get_notification(job.id)
    assert fetched.status == STATUS_RETRYING
    assert fetched.attempt_count == 1
    assert fetched.next_attempt_at == datetime(2026, 5, 7, 10, 1, 0, tzinfo=timezone.utc)
    assert fetched.last_status_code == 503
    assert len(fetched.attempts) == 1


def test_worker_fails_permanent_4xx_without_retry(session):
    repo = NotificationRepository(session)
    now = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
    job = repo.create_notification(
        target_url="https://vendor.example.test/webhook",
        method="POST",
        headers={},
        body={},
        idempotency_key=None,
        max_attempts=5,
        now=now - timedelta(minutes=1),
    )
    worker = NotificationWorker(
        repo,
        dispatcher=FakeDispatcher([DispatchResult(status_code=400, error=None, duration_ms=8)]),
    )

    worker.run_once(now=now)

    fetched = repo.get_notification(job.id)
    assert fetched.status == STATUS_FAILED
    assert fetched.attempt_count == 1
    assert fetched.last_status_code == 400
    assert len(fetched.attempts) == 1


def test_api_accepts_notification_and_returns_status(session):
    app = create_app(session_factory=lambda: session)
    client = TestClient(app)

    response = client.post(
        "/notifications",
        json={
            "target_url": "https://vendor.example.test/webhook",
            "method": "POST",
            "headers": {"Authorization": "Bearer token"},
            "body": {"event": "user_registered"},
            "idempotency_key": "user_registered:u_1",
        },
    )

    assert response.status_code == 202
    notification_id = response.json()["id"]
    detail = client.get(f"/notifications/{notification_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == STATUS_PENDING
    assert payload["target_url"] == "https://vendor.example.test/webhook"
    assert payload["attempts"] == []
