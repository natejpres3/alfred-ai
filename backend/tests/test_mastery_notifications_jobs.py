from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db import session_scope, utcnow
from app.email.providers import ConsoleProvider
from app.models import BackgroundJob, EmailDelivery, MasteryRecord, Notification, User, UserPreferences
from app.services import jobs, mastery
from app.services.notifications import next_delivery_time, notify


def test_update_estimate_recency_weighting():
    rec = MasteryRecord(estimate=0.0, evidence_weight=0.0, evidence_count=0, prior=None)
    now = utcnow()
    mastery.update_estimate(rec, 0.4, 1.0, now)
    assert rec.estimate == pytest.approx(0.4)  # first evidence is taken at face value
    for _ in range(10):
        mastery.update_estimate(rec, 1.0, 1.0, now)
    assert rec.estimate > 0.95  # the alpha floor keeps the estimate responsive


def test_retrievability_and_states(db):
    u = User(email="m@example.com", password_hash="x")
    db.add(u)
    db.flush()
    c = mastery.record(db, u.id, "concept", "la.dot_product")
    past = utcnow() - timedelta(days=10)
    c.state, c.mastered_at, c.last_evidence_at, c.stability_days, c.next_review_at = "mastered", past, past, 2.0, past + timedelta(days=2)
    db.flush()
    assert mastery.refresh_states(db, u.id) == ["la.dot_product"]
    assert c.state == "at_risk"  # exp(-10/2) ≈ 0.007


def test_next_delivery_time_respects_timezone():
    now = datetime(2026, 11, 8, 20, 0, tzinfo=UTC)  # 14:00 in Chicago (CST)
    t = next_delivery_time(now, "America/Chicago", 7)
    assert t == datetime(2026, 11, 9, 13, 0, tzinfo=UTC)
    assert next_delivery_time(now, "Asia/Tokyo", 7) == datetime(2026, 11, 8, 22, 0, tzinfo=UTC)


def _user(db, **prefs):
    u = User(email=f"n{datetime.now().timestamp()}@example.com", password_hash="x")
    db.add(u)
    db.flush()
    db.add(UserPreferences(user_id=u.id, **prefs))
    db.flush()
    return u


def test_notify_is_idempotent_and_sends_once(db, outbox):
    u = _user(db)
    for _ in range(3):
        notify(db, u.id, "lesson_passed", "k1", {"lesson_title": "L", "score": 0.9})
    db.commit()
    jobs.drain()
    assert db.scalar(select(func.count(Notification.id))) == 1
    assert len(outbox) == 1


def test_preferences_suppress_and_scheduled_delivery(db, outbox):
    u = _user(db, notify={"lesson_passed": False})
    n = notify(db, u.id, "lesson_passed", "k2", {"lesson_title": "L", "score": 0.9})
    v = _user(db, delivery_mode="scheduled", delivery_hour=7, timezone="UTC")
    m = notify(db, v.id, "lesson_available", "k3", {"lesson_title": "L", "lesson_id": "x"})
    db.commit()
    jobs.drain()
    db.refresh(n)
    db.refresh(m)
    assert n.status == "suppressed" and outbox == []
    assert m.status == "pending" and m.scheduled_for > utcnow()


def test_email_failure_is_retried_and_recorded(db, outbox, monkeypatch):
    u = _user(db)
    calls = {"n": 0}
    orig = ConsoleProvider.send

    def flaky(self, msg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider down")
        return orig(self, msg)

    monkeypatch.setattr(ConsoleProvider, "send", flaky)
    notify(db, u.id, "lesson_passed", "k4", {"lesson_title": "L", "score": 1.0})
    db.commit()
    jobs.drain()
    with session_scope() as s:
        job = s.scalar(select(BackgroundJob).where(BackgroundJob.kind == "send_notification"))
        job.run_at = utcnow()  # skip the backoff
    jobs.drain()
    statuses = [d.status for d in db.scalars(select(EmailDelivery).order_by(EmailDelivery.attempt))]
    assert statuses == ["failed", "sent"] and len(outbox) == 1


def test_jobs_idempotent_enqueue_retry_and_dead(db):
    attempts = {"n": 0}

    @jobs.handler("test_flaky")
    def flaky(session, payload):
        attempts["n"] += 1
        raise RuntimeError("boom")

    a = jobs.enqueue(db, "test_flaky", {}, key="once", max_attempts=2)
    b = jobs.enqueue(db, "test_flaky", {}, key="once")
    db.commit()
    assert a.id == b.id
    jobs.run_one()
    with session_scope() as s:
        j = s.get(BackgroundJob, a.id)
        assert j.status == "queued" and j.run_at > utcnow()
        j.run_at = utcnow()
    jobs.run_one()
    with session_scope() as s:
        assert s.get(BackgroundJob, a.id).status == "dead"
    assert attempts["n"] == 2


def test_stale_lease_is_reclaimed(db):
    @jobs.handler("test_ok")
    def ok(session, payload):
        return {"ok": True}

    j = jobs.enqueue(db, "test_ok", {})
    j.status, j.locked_at = "running", utcnow() - timedelta(hours=1)  # a worker died mid-job
    db.commit()
    assert jobs.run_one().status == "succeeded"
