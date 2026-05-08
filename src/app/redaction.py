from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "cookie",
    "token",
    "password",
    "secret",
    "api-key",
    "apikey",
    "x-api-key",
)

REDACTED_VALUE = "<redacted>"


def redact_sensitive_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED_VALUE if _should_redact_key(str(key)) else redact_sensitive_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    return value


def _should_redact_key(key: str) -> bool:
    lowered = key.replace("_", "-").lower()
    return any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS)
