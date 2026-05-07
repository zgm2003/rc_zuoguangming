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
        seconds = self.base_delay_seconds * (2**exponent)
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
