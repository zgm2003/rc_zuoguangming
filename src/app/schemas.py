from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator

from src.app.config import settings
from src.app.models import ALLOWED_METHODS
from src.app.target_url_policy import validate_target_url_allowed


class NotificationCreate(BaseModel):
    target_url: HttpUrl
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    max_attempts: int = settings.default_max_attempts

    @field_validator("method")
    @classmethod
    def validate_method(cls, value: str) -> str:
        method = value.upper()
        if method not in ALLOWED_METHODS:
            allowed = ", ".join(sorted(ALLOWED_METHODS))
            raise ValueError(f"method must be one of: {allowed}")
        return method

    @field_validator("max_attempts")
    @classmethod
    def validate_max_attempts(cls, value: int) -> int:
        if value < 1 or value > 20:
            raise ValueError("max_attempts must be between 1 and 20")
        return value

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, value: HttpUrl) -> HttpUrl:
        validate_target_url_allowed(str(value))
        return value


class NotificationAccepted(BaseModel):
    id: str
    status: str


class AttemptRead(BaseModel):
    attempt_no: int
    status_code: int | None
    error: str | None
    duration_ms: int
    created_at: datetime


class NotificationRead(BaseModel):
    id: str
    target_url: str
    method: str
    headers: dict[str, str]
    body: dict[str, Any]
    idempotency_key: str | None
    status: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime
    processing_started_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    attempts: list[AttemptRead]
