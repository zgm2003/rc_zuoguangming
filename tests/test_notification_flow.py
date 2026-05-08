from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from src.app.dispatcher import DispatchResult
from src.app.main import create_app
from src.app.models import Notification, STATUS_FAILED, STATUS_PENDING, STATUS_PROCESSING, STATUS_RETRYING
from src.app.repository import NotificationRepository
from src.app.worker import NotificationWorker
from src.app.worker_runner import run_worker_loop


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


def test_repository_reuses_existing_notification_for_same_idempotency_key(session):
    repo = NotificationRepository(session)

    first = repo.create_notification(
        target_url="https://vendor.example.test/webhook",
        method="POST",
        headers={"Authorization": "Bearer first"},
        body={"event": "user_registered"},
        idempotency_key="user_registered:u_1",
        max_attempts=5,
    )
    second = repo.create_notification(
        target_url="https://vendor.example.test/duplicate",
        method="POST",
        headers={"Authorization": "Bearer second"},
        body={"event": "duplicate"},
        idempotency_key="user_registered:u_1",
        max_attempts=5,
    )

    row_count = session.execute(select(func.count(Notification.id))).scalar_one()

    assert second.id == first.id
    assert second.target_url == "https://vendor.example.test/webhook"
    assert row_count == 1


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


class RaisingDispatcher:
    def __init__(self):
        self.calls = []

    def dispatch(self, notification):
        self.calls.append(notification.id)
        raise RuntimeError("dispatcher crashed before HTTP result")


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
    assert fetched.attempts[0].error is None
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
    assert fetched.attempts[0].error is None


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


def test_worker_does_not_consume_attempt_when_dispatcher_crashes_before_result(session):
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
    dispatcher = RaisingDispatcher()
    worker = NotificationWorker(repo, dispatcher=dispatcher)

    with pytest.raises(RuntimeError, match="dispatcher crashed"):
        worker.run_once(now=now)

    fetched = repo.get_notification(job.id)
    assert dispatcher.calls == [job.id]
    assert fetched.status == STATUS_PROCESSING
    assert fetched.attempt_count == 0
    assert fetched.attempts == []


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


def test_api_redacts_sensitive_headers_and_body_in_status_response(session):
    app = create_app(session_factory=lambda: session)
    client = TestClient(app)

    response = client.post(
        "/notifications",
        json={
            "target_url": "https://vendor.example.test/webhook",
            "method": "POST",
            "headers": {
                "Authorization": "Bearer token",
                "Cookie": "session=secret",
                "X-API-Key": "api-secret",
                "X-Trace-Id": "trace-1",
            },
            "body": {
                "event": "user_registered",
                "token": "body-token",
                "nested": {
                    "password": "body-password",
                    "secret": "body-secret",
                    "safe": "visible",
                },
            },
            "idempotency_key": "user_registered:redacted",
        },
    )

    notification_id = response.json()["id"]
    detail = client.get(f"/notifications/{notification_id}")
    payload = detail.json()

    assert payload["headers"]["Authorization"] == "<redacted>"
    assert payload["headers"]["Cookie"] == "<redacted>"
    assert payload["headers"]["X-API-Key"] == "<redacted>"
    assert payload["headers"]["X-Trace-Id"] == "trace-1"
    assert payload["body"]["event"] == "user_registered"
    assert payload["body"]["token"] == "<redacted>"
    assert payload["body"]["nested"]["password"] == "<redacted>"
    assert payload["body"]["nested"]["secret"] == "<redacted>"
    assert payload["body"]["nested"]["safe"] == "visible"


class FakeWorker:
    def __init__(self):
        self.calls = 0

    def run_once(self):
        self.calls += 1
        return 0


def test_worker_runner_loops_until_stop_event_is_set():
    worker = FakeWorker()
    sleep_calls = []

    class StopAfterThreeSleeps:
        def __init__(self):
            self.count = 0

        def is_set(self):
            return self.count >= 3

    stop_event = StopAfterThreeSleeps()

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        stop_event.count += 1

    iterations = run_worker_loop(
        worker,
        poll_interval_seconds=0.25,
        stop_event=stop_event,
        sleep=fake_sleep,
    )

    assert iterations == 3
    assert worker.calls == 3
    assert sleep_calls == [0.25, 0.25, 0.25]


class FailsOnceWorker:
    def __init__(self):
        self.calls = 0

    def run_once(self):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary database hiccup")
        return 2


def test_worker_runner_continues_after_iteration_error():
    worker = FailsOnceWorker()
    sleep_calls = []

    class StopAfterTwoSleeps:
        def __init__(self):
            self.count = 0

        def is_set(self):
            return self.count >= 2

    stop_event = StopAfterTwoSleeps()

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        stop_event.count += 1

    iterations = run_worker_loop(
        worker,
        poll_interval_seconds=0.25,
        stop_event=stop_event,
        sleep=fake_sleep,
    )

    assert iterations == 2
    assert worker.calls == 2
    assert sleep_calls == [0.25, 0.25]
