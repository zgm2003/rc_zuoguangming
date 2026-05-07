from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./notification_service.db"
    request_timeout_seconds: float = 5.0
    worker_batch_size: int = 10
    worker_poll_interval_seconds: float = 1.0
    processing_visibility_timeout_seconds: int = 300
    retry_base_delay_seconds: int = 60
    retry_max_delay_seconds: int = 3600
    default_max_attempts: int = 5

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
        )


settings = Settings.from_env()
