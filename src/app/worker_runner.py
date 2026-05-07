from __future__ import annotations

import argparse
import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Callable, Protocol

from src.app.config import settings
from src.app.database import SessionLocal, init_db
from src.app.dispatcher import HttpDispatcher
from src.app.repository import NotificationRepository
from src.app.retry_policy import RetryPolicy
from src.app.worker import NotificationWorker

logger = logging.getLogger(__name__)


class LoopWorker(Protocol):
    def run_once(self) -> int:
        raise NotImplementedError


def run_worker_loop(
    worker: LoopWorker,
    *,
    poll_interval_seconds: float,
    stop_event: Event,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    iterations = 0
    while not stop_event.is_set():
        processed = worker.run_once()
        iterations += 1
        logger.info("worker iteration=%s processed=%s", iterations, processed)
        sleep(poll_interval_seconds)
    return iterations


class ManagedWorker:
    def __init__(self, *, batch_size: int, timeout_seconds: float, visibility_timeout_seconds: int):
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds
        self.visibility_timeout_seconds = visibility_timeout_seconds

    def run_once(self) -> int:
        now = datetime.now(timezone.utc)
        with SessionLocal() as session:
            repo = NotificationRepository(session)
            stale_before = now - timedelta(seconds=self.visibility_timeout_seconds)
            recovered = repo.recover_stale_processing(stale_before=stale_before, now=now)
            if recovered:
                logger.warning("recovered stale processing notifications count=%s", recovered)
            worker = NotificationWorker(
                repo,
                dispatcher=HttpDispatcher(timeout_seconds=self.timeout_seconds),
                retry_policy=RetryPolicy(
                    base_delay_seconds=settings.retry_base_delay_seconds,
                    max_delay_seconds=settings.retry_max_delay_seconds,
                ),
                batch_size=self.batch_size,
            )
            return worker.run_once(now=now)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the reliable notification worker loop.")
    parser.add_argument("--poll-interval", type=float, default=settings.worker_poll_interval_seconds)
    parser.add_argument("--batch-size", type=int, default=settings.worker_batch_size)
    parser.add_argument("--timeout", type=float, default=settings.request_timeout_seconds)
    parser.add_argument(
        "--visibility-timeout",
        type=int,
        default=settings.processing_visibility_timeout_seconds,
        help="seconds before a processing notification is considered stale",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_arg_parser().parse_args()
    init_db()
    stop_event = Event()

    def request_stop(signum, frame):
        logger.info("received signal=%s, stopping worker", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    logger.info(
        "starting notification worker poll_interval=%s batch_size=%s timeout=%s visibility_timeout=%s",
        args.poll_interval,
        args.batch_size,
        args.timeout,
        args.visibility_timeout,
    )
    run_worker_loop(
        ManagedWorker(
            batch_size=args.batch_size,
            timeout_seconds=args.timeout,
            visibility_timeout_seconds=args.visibility_timeout,
        ),
        poll_interval_seconds=args.poll_interval,
        stop_event=stop_event,
    )
    logger.info("notification worker stopped")


if __name__ == "__main__":
    main()
