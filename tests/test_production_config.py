import os

from src.app.config import Settings
from src.app.database import build_engine_kwargs, is_sqlite_url
from src.app.repository import build_claim_statement
from src.app.models import Notification
from sqlalchemy.dialects import postgresql


def test_settings_default_to_local_sqlite_when_env_is_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings.from_env()

    assert settings.database_url == "sqlite:///./notification_service.db"


def test_settings_read_database_url_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://notify:secret@127.0.0.1:5432/notify_db")

    settings = Settings.from_env()

    assert settings.database_url == "postgresql+psycopg://notify:secret@127.0.0.1:5432/notify_db"


def test_sqlite_engine_uses_check_same_thread_false():
    kwargs = build_engine_kwargs("sqlite:///./notification_service.db")

    assert kwargs["connect_args"] == {"check_same_thread": False}
    assert kwargs["future"] is True


def test_postgres_engine_does_not_use_sqlite_connect_args():
    kwargs = build_engine_kwargs("postgresql+psycopg://notify:secret@127.0.0.1:5432/notify_db")

    assert "connect_args" not in kwargs
    assert kwargs["future"] is True


def test_database_url_type_detection():
    assert is_sqlite_url("sqlite:///./notification_service.db") is True
    assert is_sqlite_url("sqlite:///:memory:") is True
    assert is_sqlite_url("postgresql+psycopg://notify:secret@127.0.0.1:5432/notify_db") is False


def test_postgres_claim_statement_uses_skip_locked():
    stmt = build_claim_statement(limit=20, use_skip_locked=True)

    compiled = str(stmt.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE SKIP LOCKED" in compiled
    assert "notifications.status IN" in compiled
    assert "notifications.next_attempt_at <=" in compiled
