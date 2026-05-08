from __future__ import annotations

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from src.app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def is_sqlite_url(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def engine_kwargs_for_url(url) -> dict:
    """Return driver-specific kwargs only; kept separate for focused tests."""
    if url.get_backend_name() == "sqlite":
        return {"connect_args": {"check_same_thread": False}}
    return {}


def build_engine_kwargs(database_url: str) -> dict:
    from sqlalchemy.engine.url import make_url

    kwargs: dict = {"future": True}
    kwargs.update(engine_kwargs_for_url(make_url(database_url)))
    return kwargs


def create_app_engine(database_url: str):
    return create_engine(database_url, **build_engine_kwargs(database_url))


engine = create_app_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    import src.app.models  # noqa: F401

    Base.metadata.create_all(engine)
    ensure_runtime_indexes()


def ensure_runtime_indexes() -> None:
    if engine.dialect.name not in {"sqlite", "postgresql"}:
        return
    if has_duplicate_idempotency_keys():
        logger.warning(
            "skip creating uq_notifications_idempotency_key because duplicate idempotency_key values already exist"
        )
        return
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_idempotency_key "
            "ON notifications (idempotency_key)"
        )


def has_duplicate_idempotency_keys() -> bool:
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            """
            SELECT 1
            FROM notifications
            WHERE idempotency_key IS NOT NULL
            GROUP BY idempotency_key
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).first()
    return row is not None


def get_session():
    with SessionLocal() as session:
        yield session
