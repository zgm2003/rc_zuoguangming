from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Response, status
from sqlalchemy.orm import Session

from src.app.database import get_session, init_db
from src.app.repository import NotificationRepository
from src.app.schemas import NotificationAccepted, NotificationCreate, NotificationRead
from src.app.redaction import redact_sensitive_data

SessionFactory = Callable[[], Session]


def create_app(session_factory: SessionFactory | None = None) -> FastAPI:
    app = FastAPI(
        title="Reliable HTTP Notification Service",
        version="1.0.0",
        description="Durable asynchronous HTTP notification delivery service.",
    )

    if session_factory is None:
        init_db()

    def session_dependency() -> Iterator[Session]:
        if session_factory is None:
            yield from get_session()
            return
        session = session_factory()
        try:
            yield session
        finally:
            pass

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/notifications", response_model=NotificationAccepted, status_code=status.HTTP_202_ACCEPTED)
    def create_notification(payload: NotificationCreate, session: Session = Depends(session_dependency)):
        repo = NotificationRepository(session)
        item = repo.create_notification(
            target_url=str(payload.target_url),
            method=payload.method,
            headers=payload.headers,
            body=payload.body,
            idempotency_key=payload.idempotency_key,
            max_attempts=payload.max_attempts,
        )
        return NotificationAccepted(id=item.id, status=item.status)

    @app.get("/notifications/{notification_id}", response_model=NotificationRead)
    def get_notification(notification_id: str, session: Session = Depends(session_dependency)):
        repo = NotificationRepository(session)
        item = repo.get_notification(notification_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="notification not found")
        return _to_read_model(item)

    return app


def _to_read_model(item) -> NotificationRead:
    return NotificationRead(
        id=item.id,
        target_url=item.target_url,
        method=item.method,
        headers=redact_sensitive_data(item.headers),
        body=redact_sensitive_data(item.body),
        idempotency_key=item.idempotency_key,
        status=item.status,
        attempt_count=item.attempt_count,
        max_attempts=item.max_attempts,
        next_attempt_at=item.next_attempt_at,
        processing_started_at=item.processing_started_at,
        last_status_code=item.last_status_code,
        last_error=item.last_error,
        created_at=item.created_at,
        updated_at=item.updated_at,
        attempts=[
            {
                "attempt_no": attempt.attempt_no,
                "status_code": attempt.status_code,
                "error": attempt.error,
                "duration_ms": attempt.duration_ms,
                "created_at": attempt.created_at,
            }
            for attempt in item.attempts
        ],
    )


app = create_app()
