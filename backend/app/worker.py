"""Background worker: executes queued jobs and enqueues periodic work.

    uv run python -m app.worker
"""

from __future__ import annotations

import logging
import signal
import time

from app.config import get_settings
from app.db import session_scope, utcnow
from app.services import jobs, workflow  # noqa: F401 - registers handlers

log = logging.getLogger("academy.worker")
_running = True


def _stop(*_):
    global _running
    _running = False


def enqueue_periodic() -> None:
    now = utcnow()
    with session_scope() as db:
        # one review scan per hour bucket; idempotency keys make concurrent workers safe
        jobs.enqueue(db, "scan_reviews", {}, key=f"scan_reviews:{now:%Y%m%d%H}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    s = get_settings()
    log.info("worker %s started (ai=%s sandbox=%s email=%s)", s.worker_id, s.ai_provider, s.sandbox_backend, s.email_provider)
    last_periodic = 0.0
    while _running:
        if time.monotonic() - last_periodic > 300:
            enqueue_periodic()
            last_periodic = time.monotonic()
        job = jobs.run_one(s.worker_id)
        if job is None:
            time.sleep(s.worker_poll_seconds)
        else:
            log.info("job %s %s → %s", job.kind, job.id, job.status)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
