import importlib

from sqlalchemy.engine.url import make_url

from src.app.config import Settings
from src.app.database import engine_kwargs_for_url


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
