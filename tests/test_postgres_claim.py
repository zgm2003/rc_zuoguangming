from sqlalchemy.dialects import postgresql

from src.app.repository import NotificationRepository


def test_postgres_claim_statement_uses_skip_locked(session):
    repo = NotificationRepository(session)

    stmt = repo._build_claim_statement(limit=10, use_skip_locked=True)
    compiled = str(stmt.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE SKIP LOCKED" in compiled


def test_sqlite_claim_statement_does_not_use_for_update(session):
    repo = NotificationRepository(session)

    stmt = repo._build_claim_statement(limit=10, use_skip_locked=False)
    compiled = str(stmt)

    assert "FOR UPDATE" not in compiled
    assert "SKIP LOCKED" not in compiled
