from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import httpx

from src.app.models import Notification


@dataclass(frozen=True)
class DispatchResult:
    status_code: int | None
    error: str | None
    duration_ms: int


class HttpDispatcher:
    def __init__(self, timeout_seconds: float = 5.0):
        self.timeout_seconds = timeout_seconds

    def dispatch(self, notification: Notification) -> DispatchResult:
        started = perf_counter()
        headers = dict(notification.headers)
        if notification.idempotency_key and "Idempotency-Key" not in headers:
            headers["Idempotency-Key"] = notification.idempotency_key

        try:
            response = httpx.request(
                notification.method,
                notification.target_url,
                headers=headers,
                json=notification.body,
                timeout=self.timeout_seconds,
            )
            return DispatchResult(
                status_code=response.status_code,
                error=None,
                duration_ms=_duration_ms(started),
            )
        except httpx.HTTPError as exc:
            return DispatchResult(
                status_code=None,
                error=str(exc),
                duration_ms=_duration_ms(started),
            )


def _duration_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))
