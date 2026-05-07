from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from src.app.models import (
    ALLOWED_METHODS,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_RETRYING,
    STATUS_SUCCEEDED,
    Notification,
    NotificationAttempt,
)

CLAIMABLE_STATUSES = {STATUS_PENDING, STATUS_RETRYING}


def build_claim_statement(*, limit: int, use_skip_locked: bool = False) -> Select[tuple[Notification]]:
    stmt: Select[tuple[Notification]] = (
        select(Notification)
        .where(Notification.status.in_(CLAIMABLE_STATUSES))
        .where(Notification.next_attempt_at <= utc_now())
        .order_by(Notification.next_attempt_at.asc(), Notification.created_at.asc())
        .limit(limit)
    )
    if use_skip_locked:
        stmt = stmt.with_for_update(skip_locked=True)
    return stmt


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class NotificationRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_notification(
        self,
        *,
        target_url: str,
        method: str,
        headers: dict[str, str],
        body: dict[str, Any],
        idempotency_key: str | None,
        max_attempts: int,
        now: datetime | None = None,
    ) -> Notification:
        method = method.upper()
        if method not in ALLOWED_METHODS:
            raise ValueError(f"unsupported HTTP method: {method}")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        now = _normalize_datetime(now or utc_now())
        item = Notification(
            id=str(uuid.uuid4()),
            target_url=target_url,
            method=method,
            headers_json=json.dumps(headers, ensure_ascii=False, sort_keys=True),
            body_json=json.dumps(body, ensure_ascii=False, sort_keys=True),
            idempotency_key=idempotency_key,
            status=STATUS_PENDING,
            attempt_count=0,
            max_attempts=max_attempts,
            next_attempt_at=now,
            processing_started_at=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def get_notification(self, notification_id: str) -> Notification | None:
        stmt = (
            select(Notification)
            .where(Notification.id == notification_id)
            .options(selectinload(Notification.attempts))
        )
        return self.session.execute(stmt.execution_options(populate_existing=True)).scalar_one_or_none()

    def claim_due_notifications(self, *, limit: int, now: datetime | None = None) -> list[Notification]:
        now = _normalize_datetime(now or utc_now())
        use_skip_locked = self.session.bind is not None and self.session.bind.dialect.name == "postgresql"
        stmt = self._build_claim_statement(limit=limit, use_skip_locked=use_skip_locked, now=now)
        items = list(self.session.execute(stmt).scalars().all())
        for item in items:
            item.status = STATUS_PROCESSING
            item.processing_started_at = now
            item.updated_at = now
        self.session.commit()
        for item in items:
            self.session.refresh(item)
        return items

    def _build_claim_statement(
        self,
        *,
        limit: int,
        use_skip_locked: bool,
        now: datetime | None = None,
    ) -> Select[tuple[Notification]]:
        now = _normalize_datetime(now or utc_now())
        stmt: Select[tuple[Notification]] = (
            select(Notification)
            .where(Notification.status.in_(CLAIMABLE_STATUSES))
            .where(Notification.next_attempt_at <= now)
            .order_by(Notification.next_attempt_at.asc(), Notification.created_at.asc())
            .limit(limit)
        )
        if use_skip_locked:
            return stmt.with_for_update(skip_locked=True)
        return stmt

    def record_attempt(
        self,
        notification_id: str,
        *,
        attempt_no: int,
        status_code: int | None,
        error: str | None,
        duration_ms: int,
        now: datetime | None = None,
    ) -> NotificationAttempt:
        now = _normalize_datetime(now or utc_now())
        attempt = NotificationAttempt(
            notification_id=notification_id,
            attempt_no=attempt_no,
            status_code=status_code,
            error=error,
            duration_ms=duration_ms,
            created_at=now,
        )
        self.session.add(attempt)
        self.session.commit()
        self.session.refresh(attempt)
        return attempt

    def mark_succeeded(self, notification_id: str, *, status_code: int | None, now: datetime | None = None) -> None:
        now = _normalize_datetime(now or utc_now())
        item = self._require(notification_id)
        item.status = STATUS_SUCCEEDED
        item.last_status_code = status_code
        item.last_error = None
        item.processing_started_at = None
        item.updated_at = now
        self.session.commit()

    def mark_failed(
        self,
        notification_id: str,
        *,
        status_code: int | None = None,
        error: str | None = None,
        now: datetime | None = None,
    ) -> None:
        now = _normalize_datetime(now or utc_now())
        item = self._require(notification_id)
        item.status = STATUS_FAILED
        item.last_status_code = status_code
        item.last_error = error
        item.processing_started_at = None
        item.updated_at = now
        self.session.commit()

    def schedule_retry(
        self,
        notification_id: str,
        *,
        next_attempt_at: datetime,
        status_code: int | None = None,
        error: str | None = None,
        now: datetime | None = None,
    ) -> None:
        now = _normalize_datetime(now or utc_now())
        item = self._require(notification_id)
        item.status = STATUS_RETRYING
        item.next_attempt_at = _normalize_datetime(next_attempt_at)
        item.last_status_code = status_code
        item.last_error = error
        item.processing_started_at = None
        item.updated_at = now
        self.session.commit()

    def increment_attempt_count(self, notification_id: str, *, now: datetime | None = None) -> int:
        now = _normalize_datetime(now or utc_now())
        item = self._require(notification_id)
        item.attempt_count += 1
        item.updated_at = now
        self.session.commit()
        return item.attempt_count

    def recover_stale_processing(self, *, stale_before: datetime, now: datetime | None = None) -> int:
        now = _normalize_datetime(now or utc_now())
        stale_before = _normalize_datetime(stale_before)
        stmt = (
            select(Notification)
            .where(Notification.status == STATUS_PROCESSING)
            .where(Notification.processing_started_at < stale_before)
        )
        items = list(self.session.execute(stmt).scalars().all())
        for item in items:
            item.status = STATUS_RETRYING
            item.next_attempt_at = now
            item.processing_started_at = None
            item.last_error = "recovered from stale processing state"
            item.updated_at = now
        self.session.commit()
        return len(items)

    def _require(self, notification_id: str) -> Notification:
        item = self.session.get(Notification, notification_id)
        if item is None:
            raise KeyError(f"notification not found: {notification_id}")
        return item
