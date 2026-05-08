from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from src.app.dispatcher import DispatchResult
from src.app.models import Notification
from src.app.repository import NotificationRepository
from src.app.retry_policy import RetryPolicy, classify_delivery


class Dispatcher(Protocol):
    def dispatch(self, notification: Notification) -> DispatchResult:
        raise NotImplementedError


class NotificationWorker:
    def __init__(
        self,
        repository: NotificationRepository,
        *,
        dispatcher: Dispatcher,
        retry_policy: RetryPolicy | None = None,
        batch_size: int = 10,
    ):
        self.repository = repository
        self.dispatcher = dispatcher
        self.retry_policy = retry_policy or RetryPolicy()
        self.batch_size = batch_size

    def run_once(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        jobs = self.repository.claim_due_notifications(limit=self.batch_size, now=now)
        for job in jobs:
            self._process(job, now=now)
        return len(jobs)

    def _process(self, notification: Notification, *, now: datetime) -> None:
        attempt_no = notification.attempt_count + 1
        result = self.dispatcher.dispatch(notification)
        outcome = classify_delivery(
            status_code=result.status_code,
            error=result.error,
            attempt_count=attempt_no,
            max_attempts=notification.max_attempts,
            now=now,
            policy=self.retry_policy,
        )
        self.repository.finish_attempt(
            notification.id,
            attempt_no=attempt_no,
            status_code=result.status_code,
            error=result.error,
            last_error=None if outcome.status == "succeeded" else result.error or outcome.reason,
            duration_ms=result.duration_ms,
            final_status=outcome.status,
            next_attempt_at=outcome.next_attempt_at,
            now=now,
        )
