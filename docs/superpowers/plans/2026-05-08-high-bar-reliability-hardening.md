# High-Bar Reliability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the concrete issues a high-bar company would penalize in the notification service: open target URLs, missing inbound idempotency, sensitive status response leakage, and attempt-count crash windows.

**Architecture:** Keep the current FastAPI + SQLAlchemy + worker design. Add small pure helpers for target URL policy and response redaction. Keep repository-owned state transitions so delivery attempts and terminal state updates are committed together.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, pytest.

---

### Task 1: Target URL policy

**Files:**
- Create: `src/app/target_url_policy.py`
- Modify: `src/app/schemas.py`
- Test: `tests/test_target_url_policy.py`

- [x] Write tests that reject loopback, private, link-local, and metadata IP URLs while allowing public HTTPS vendor URLs.
- [x] Run `python -m pytest tests/test_target_url_policy.py -q` and verify failures before implementation.
- [x] Implement `validate_target_url_allowed()` as a pure Pydantic validator helper.
- [x] Re-run target tests.

### Task 2: Inbound idempotency

**Files:**
- Modify: `src/app/models.py`
- Modify: `src/app/repository.py`
- Test: `tests/test_notification_flow.py`

- [x] Add a test showing two create calls with the same `idempotency_key` return the same notification row and do not create duplicates.
- [x] Run the specific test and verify it fails first.
- [x] Add a nullable unique constraint on `idempotency_key` and repository pre-check/IntegrityError fallback.
- [x] Re-run the specific test.

### Task 3: Redact sensitive response fields

**Files:**
- Create: `src/app/redaction.py`
- Modify: `src/app/main.py`
- Test: `tests/test_notification_flow.py`

- [x] Add an API test proving `Authorization`, `Cookie`, `token`, `password`, and `secret` are redacted in GET responses.
- [x] Run the specific test and verify it fails first.
- [x] Apply redaction only to read-model output; persisted dispatch payload remains unchanged.
- [x] Re-run the specific test.

### Task 4: Attempt accounting crash window

**Files:**
- Modify: `src/app/repository.py`
- Modify: `src/app/worker.py`
- Test: `tests/test_notification_flow.py`

- [x] Add a worker test where dispatcher raises before any HTTP result and assert no attempt count/attempt row is consumed.
- [x] Run the specific test and verify it fails first.
- [x] Replace pre-dispatch `increment_attempt_count()` with post-dispatch atomic `finish_attempt()`.
- [x] Re-run worker flow tests.

### Task 5: Verification

**Files:**
- All changed files

- [x] Run `python -m pytest -q`.
- [x] Inspect `git diff --stat` and focused diff.
- [x] Report exact evidence and revised score.
