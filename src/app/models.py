from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.database import Base

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_SUCCEEDED = "succeeded"
STATUS_RETRYING = "retrying"
STATUS_FAILED = "failed"

ALLOWED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class UTCDateTime(TypeDecorator):
    """Store datetimes as UTC and always return timezone-aware values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_notifications_idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    headers_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    body_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    attempts: Mapped[list["NotificationAttempt"]] = relationship(
        back_populates="notification",
        cascade="all, delete-orphan",
        order_by="NotificationAttempt.attempt_no",
        lazy="selectin",
    )

    @property
    def headers(self) -> dict[str, str]:
        return json.loads(self.headers_json)

    @property
    def body(self) -> dict[str, Any]:
        return json.loads(self.body_json)


class NotificationAttempt(Base):
    __tablename__ = "notification_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notification_id: Mapped[str] = mapped_column(String(36), ForeignKey("notifications.id"), nullable=False, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    notification: Mapped[Notification] = relationship(back_populates="attempts")
