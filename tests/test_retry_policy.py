from datetime import datetime, timezone

from src.app.retry_policy import RetryPolicy, classify_delivery


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
