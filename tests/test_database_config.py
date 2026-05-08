import importlib

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker

from src.app.config import Settings
from src.app.database import engine_kwargs_for_url
from src.app.repository import NotificationRepository


def test_settings_default_to_local_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings.from_env()

    assert settings.database_url == "sqlite:///./notification_service.db"


def test_settings_read_database_url_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://notify:secret@db/notify")

    settings = Settings.from_env()

    assert settings.database_url == "postgresql+psycopg://notify:secret@db/notify"


def test_sqlite_engine_keeps_check_same_thread_disabled():
    kwargs = engine_kwargs_for_url(make_url("sqlite:///./notification_service.db"))

    assert kwargs == {"connect_args": {"check_same_thread": False}}


def test_postgres_engine_does_not_receive_sqlite_connect_args():
    kwargs = engine_kwargs_for_url(make_url("postgresql+psycopg://notify:secret@db/notify"))

    assert kwargs == {}


def test_init_db_creates_named_idempotency_unique_index(tmp_path, monkeypatch):
    import src.app.database as database_module

    temp_engine = create_engine(f"sqlite:///{tmp_path / 'notification.db'}", future=True)
    monkeypatch.setattr(database_module, "engine", temp_engine)

    database_module.init_db()

    with temp_engine.connect() as connection:
        indexes = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'notifications'"
        ).scalars().all()

    assert "uq_notifications_idempotency_key" in indexes


def test_init_db_skips_unique_index_creation_when_duplicate_idempotency_keys_exist(tmp_path, monkeypatch):
    import src.app.database as database_module
    temp_engine = create_engine(f"sqlite:///{tmp_path / 'duplicate-notification.db'}", future=True)
    with temp_engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE notifications (
                id VARCHAR(36) PRIMARY KEY,
                target_url TEXT NOT NULL,
                method VARCHAR(10) NOT NULL,
                headers_json TEXT NOT NULL DEFAULT '{}',
                body_json TEXT NOT NULL DEFAULT '{}',
                idempotency_key VARCHAR(255),
                status VARCHAR(20) NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                next_attempt_at DATETIME NOT NULL,
                processing_started_at DATETIME,
                last_status_code INTEGER,
                last_error TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        for id_ in ("a", "b"):
            connection.exec_driver_sql(
                """
                INSERT INTO notifications (
                    id, target_url, method, headers_json, body_json, idempotency_key,
                    status, attempt_count, max_attempts, next_attempt_at, created_at, updated_at
                ) VALUES (?, 'https://vendor.example.test/webhook', 'POST', '{}', '{}', 'dup-key',
                          'pending', 0, 5, '2026-05-08 00:00:00', '2026-05-08 00:00:00', '2026-05-08 00:00:00')
                """,
                (id_,),
            )

    monkeypatch.setattr(database_module, "engine", temp_engine)

    database_module.init_db()

    with temp_engine.connect() as connection:
        indexes = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'notifications'"
        ).scalars().all()

    assert "uq_notifications_idempotency_key" not in indexes

    SessionLocal = sessionmaker(bind=temp_engine, expire_on_commit=False, future=True)
    with SessionLocal() as session:
        repo = NotificationRepository(session)
        existing = repo.create_notification(
            target_url="https://vendor.example.test/new-webhook",
            method="POST",
            headers={},
            body={},
            idempotency_key="dup-key",
            max_attempts=5,
        )
        row_count = session.execute(text("SELECT COUNT(*) FROM notifications")).scalar_one()

    assert existing.id == "a"
    assert row_count == 2


def test_database_module_uses_database_url_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./tmp/test-env-notification.db")

    import src.app.config as config_module
    import src.app.database as database_module

    importlib.reload(config_module)
    reloaded_database = importlib.reload(database_module)

    assert str(reloaded_database.engine.url) == "sqlite:///./tmp/test-env-notification.db"

    monkeypatch.delenv("DATABASE_URL", raising=False)
    importlib.reload(config_module)
    importlib.reload(database_module)
