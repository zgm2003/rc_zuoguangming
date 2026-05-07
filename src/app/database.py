from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from src.app.config import settings


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
    Base.metadata.create_all(engine)


def get_session():
    with SessionLocal() as session:
        yield session
