from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, JSONType


class Notification(Base):
    __tablename__ = "notifications"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    scheduled_for: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|sent|suppressed|failed
    read_at: Mapped[datetime | None]


class EmailDelivery(Base):
    __tablename__ = "email_deliveries"

    notification_id: Mapped[str] = mapped_column(ForeignKey("notifications.id"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    to_address: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12))  # sent|failed
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None]


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_at: Mapped[datetime] = mapped_column(index=True)
    locked_at: Mapped[datetime | None]
    locked_by: Mapped[str | None] = mapped_column(String(120))
    last_error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    result: Mapped[dict] = mapped_column(JSONType, default=dict)
    finished_at: Mapped[datetime | None]


class AuditEvent(Base):
    __tablename__ = "audit_events"

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor: Mapped[str] = mapped_column(String(16))  # system|user|ai|admin
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSONType, default=dict)


class AICall(Base):
    __tablename__ = "ai_calls"

    role: Mapped[str] = mapped_column(String(24), index=True)
    model: Mapped[str] = mapped_column(String(60))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16))  # ok|error|refusal|budget|invalid
    error: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(120))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    context: Mapped[dict] = mapped_column(JSONType, default=dict)
