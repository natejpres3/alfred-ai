"""Postgres-backed job queue (see docs: PRD assumption 2).

enqueue() is called inside the caller's transaction, so a job exists iff the state change that
caused it committed. claim() uses SELECT … FOR UPDATE SKIP LOCKED on Postgres; on SQLite (tests)
a plain select is fine because there is a single worker.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import session_scope, utcnow
from app.models import BackgroundJob

log = logging.getLogger("academy.jobs")
LEASE = timedelta(minutes=15)
HANDLERS: dict[str, Callable[[Session, dict], dict | None]] = {}


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn

    return deco


def enqueue(db: Session, kind: str, payload: dict, *, key: str | None = None, run_at=None, max_attempts: int = 5) -> BackgroundJob | None:
    """Idempotent when `key` is given: a second enqueue with the same key is a no-op."""
    if key:
        existing = db.scalar(select(BackgroundJob).where(BackgroundJob.idempotency_key == key))
        if existing:
            return existing
    job = BackgroundJob(kind=kind, payload=payload, idempotency_key=key, run_at=run_at or utcnow(), max_attempts=max_attempts)
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:
        return db.scalar(select(BackgroundJob).where(BackgroundJob.idempotency_key == key))
    return job


def claim(db: Session, worker_id: str) -> BackgroundJob | None:
    now = utcnow()
    q = (
        select(BackgroundJob)
        .where(
            or_(
                (BackgroundJob.status == "queued") & (BackgroundJob.run_at <= now),
                (BackgroundJob.status == "running") & (BackgroundJob.locked_at < now - LEASE),  # stale lease
            )
        )
        .order_by(BackgroundJob.run_at)
        .limit(1)
    )
    if db.bind.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    job = db.scalar(q)
    if job is None:
        return None
    job.status, job.locked_at, job.locked_by = "running", now, worker_id
    job.attempts += 1
    db.commit()
    return job


def run_one(worker_id: str = "inline") -> BackgroundJob | None:
    """Claim and execute one job. Returns the job (or None if the queue is empty)."""
    with session_scope() as db:
        job = claim(db, worker_id)
        if job is None:
            return None
        job_id, kind, payload = job.id, job.kind, dict(job.payload)
    fn = HANDLERS.get(kind)
    try:
        if fn is None:
            raise RuntimeError(f"no handler for job kind {kind}")
        with session_scope() as db:
            result = fn(db, payload) or {}
        with session_scope() as db:
            j = db.get(BackgroundJob, job_id)
            j.status, j.result, j.finished_at, j.last_error = "succeeded", result, utcnow(), None
            return j
    except Exception as e:  # noqa: BLE001 - every failure is recorded and retried
        retryable = getattr(e, "retryable", True)
        log.exception("job %s (%s) failed", job_id, kind)
        with session_scope() as db:
            j = db.get(BackgroundJob, job_id)
            j.last_error = "".join(traceback.format_exception_only(type(e), e))[-2000:]
            if retryable and j.attempts < j.max_attempts:
                j.status = "queued"
                j.run_at = utcnow() + timedelta(seconds=min(3600, 15 * 2 ** (j.attempts - 1)))
            else:
                j.status = "dead"
                j.finished_at = utcnow()
                on_dead = HANDLERS.get(f"{kind}:dead")
                if on_dead:
                    on_dead(db, payload | {"error": j.last_error})
            return j


def drain(max_jobs: int = 200) -> int:
    """Run queued jobs until empty (used by tests and the dev 'inline' mode)."""
    n = 0
    while n < max_jobs:
        job = run_one()
        if job is None:
            break
        n += 1
    return n
