from __future__ import annotations

import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.app.database import Base, build_engine_kwargs
from src.app.models import Notification, STATUS_PROCESSING, STATUS_PENDING
from src.app.repository import NotificationRepository

DEFAULT_DATABASE_URL = "postgresql+psycopg://notify_user:notify_password@127.0.0.1:5432/notify_db"


def seed_notifications(session_factory, total: int) -> list[str]:
    ids: list[str] = []
    due_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with session_factory() as session:
        repo = NotificationRepository(session)
        for index in range(total):
            item = repo.create_notification(
                target_url="https://vendor.example.test/webhook",
                method="POST",
                headers={},
                body={"index": index},
                idempotency_key=f"concurrency:{index}",
                max_attempts=5,
                now=due_at,
            )
            ids.append(item.id)
    return ids


def claim_batch(session_factory, worker_no: int, batch_size: int) -> list[str]:
    with session_factory() as session:
        repo = NotificationRepository(session)
        claimed = repo.claim_due_notifications(limit=batch_size, now=datetime.now(timezone.utc))
        return [item.id for item in claimed]


def main() -> None:
    # Verifies the Postgres multi-worker claim path. Success criteria:
    # multiple concurrent workers claim due jobs without duplicate IDs, relying on FOR UPDATE SKIP LOCKED.
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    if not database_url.startswith("postgresql"):
        raise SystemExit("DATABASE_URL must point to Postgres for this concurrency check")

    engine = create_engine(database_url, **build_engine_kwargs(database_url))
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    total_jobs = int(os.getenv("CONCURRENCY_CHECK_JOBS", "100"))
    worker_count = int(os.getenv("CONCURRENCY_CHECK_WORKERS", "8"))
    batch_size = int(os.getenv("CONCURRENCY_CHECK_BATCH_SIZE", "20"))

    seeded_ids = seed_notifications(SessionLocal, total_jobs)

    claimed_ids: list[str] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(claim_batch, SessionLocal, worker_no, batch_size) for worker_no in range(worker_count)]
        for future in as_completed(futures):
            claimed_ids.extend(future.result())

    duplicates = len(claimed_ids) - len(set(claimed_ids))
    with SessionLocal() as session:
        processing_count = session.execute(
            select(Notification).where(Notification.id.in_(seeded_ids)).where(Notification.status == STATUS_PROCESSING)
        ).scalars().all()
        pending_count = session.execute(
            select(Notification).where(Notification.id.in_(seeded_ids)).where(Notification.status == STATUS_PENDING)
        ).scalars().all()

    print(f"seeded={len(seeded_ids)} claimed={len(claimed_ids)} unique_claimed={len(set(claimed_ids))} duplicate_claims={duplicates}")
    print(f"processing={len(processing_count)} pending={len(pending_count)}")

    if duplicates != 0:
        raise SystemExit("duplicate claim detected; FOR UPDATE SKIP LOCKED path is not safe")
    if len(claimed_ids) == 0:
        raise SystemExit("no jobs were claimed; concurrency check did not exercise the worker claim path")


if __name__ == "__main__":
    main()
