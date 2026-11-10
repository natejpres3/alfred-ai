"""Notification Service: idempotent notifications, preferences, delivery hours, email sending."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.email.providers import OutgoingEmail, get_email_provider
from app.email.templates import render
from app.models import Block, EmailDelivery, Lesson, LessonVersion, Module, Notification, User, UserPreferences
from app.services import jobs

SCHEDULABLE = {"lesson_available", "review_due"}  # respect the delivery hour; others go immediately
ALWAYS_SEND = {"verify_email"}


def next_delivery_time(now: datetime, tz: str, hour: int) -> datetime:
    local = now.astimezone(ZoneInfo(tz))
    target = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target.astimezone(ZoneInfo("UTC"))


def notify(db: Session, user_id: str, kind: str, key: str, payload: dict) -> Notification:
    """Create a notification exactly once per idempotency key and schedule its delivery."""
    existing = db.scalar(select(Notification).where(Notification.idempotency_key == key))
    if existing:
        return existing
    prefs = db.scalar(select(UserPreferences).where(UserPreferences.user_id == user_id))
    now = utcnow()
    when = now
    if prefs and kind in SCHEDULABLE and prefs.delivery_mode == "scheduled":
        when = next_delivery_time(now, prefs.timezone, prefs.delivery_hour)
    n = Notification(user_id=user_id, kind=kind, idempotency_key=key, payload=payload, scheduled_for=when, status="pending")
    db.add(n)
    db.flush()
    jobs.enqueue(db, "send_notification", {"notification_id": n.id}, key=f"send:{n.id}", run_at=when, max_attempts=6)
    return n


def notify_lesson_available(db: Session, user_id: str, lesson: Lesson, version: LessonVersion) -> Notification:
    module = db.get(Module, lesson.module_id)
    block = db.get(Block, module.block_id)
    c = version.content
    return notify(db, user_id, "lesson_available", f"lesson_available:{user_id}:{lesson.id}", {
        "lesson_id": lesson.id, "lesson_title": c.get("title", lesson.title), "block": block.title, "module": module.title,
        "minutes": c.get("estimated_minutes", 60), "why": c.get("why_it_matters", ""),
        "objectives": [o["statement"] for o in c.get("objectives", [])],
        "connections": [x["note"] for x in c.get("connections", []) if x.get("direction") == "builds_on"],
    })


def send_notification(db: Session, notification_id: str) -> dict:
    n = db.get(Notification, notification_id)
    if n is None or n.status != "pending":
        return {"skipped": n.status if n else "missing"}
    if db.scalar(select(EmailDelivery).where(EmailDelivery.notification_id == n.id, EmailDelivery.status == "sent")):
        n.status = "sent"
        return {"skipped": "already delivered"}
    user = db.get(User, n.user_id)
    prefs = db.scalar(select(UserPreferences).where(UserPreferences.user_id == n.user_id))
    if n.kind not in ALWAYS_SEND and (prefs is None or not prefs.email_enabled or not prefs.notify.get(n.kind, True)):
        n.status = "suppressed"
        return {"suppressed": True}
    subject, html, text = render(n.kind, n.payload, prefs.unsubscribe_token if prefs else "")
    provider = get_email_provider()
    attempt = len(db.scalars(select(EmailDelivery).where(EmailDelivery.notification_id == n.id)).all()) + 1
    headers = {}
    if prefs:
        web = get_settings().public_web_url.rstrip("/")
        headers["List-Unsubscribe"] = f"<{web}/api/email/unsubscribe?token={prefs.unsubscribe_token}>"
    try:
        mid = provider.send(OutgoingEmail(to=user.email, subject=subject, html=html, text=text,
                                          idempotency_key=n.idempotency_key, headers=headers))
    except Exception as e:
        db.add(EmailDelivery(notification_id=n.id, provider=provider.name, to_address=user.email, subject=subject,
                             status="failed", attempt=attempt, error=str(e)[:1000]))
        db.commit()  # keep the failure record even though the job will be retried
        raise
    db.add(EmailDelivery(notification_id=n.id, provider=provider.name, provider_message_id=mid, to_address=user.email,
                         subject=subject, status="sent", attempt=attempt, sent_at=utcnow()))
    n.status = "sent"
    return {"sent": mid}


def mark_failed(db: Session, payload: dict) -> None:
    n = db.get(Notification, payload["notification_id"])
    if n and n.status == "pending":
        n.status = "failed"
