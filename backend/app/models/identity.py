from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType, new_id


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    email_verified_at: Mapped[datetime | None]
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    preferences: Mapped[UserPreferences] = relationship(back_populates="user", uselist=False)
    profile: Mapped[LearningProfile] = relationship(back_populates="user", uselist=False)


class UserSession(Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


DEFAULT_NOTIFY = {
    "lesson_available": True,
    "submission_graded": True,
    "lesson_passed": True,
    "remediation_required": True,
    "module_completed": True,
    "section_unlocked": True,
    "project_graded": True,
    "review_due": True,
}


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    daily_goal_minutes: Mapped[int] = mapped_column(Integer, default=60)
    delivery_mode: Mapped[str] = mapped_column(String(16), default="immediate")  # immediate|scheduled
    delivery_hour: Mapped[int] = mapped_column(Integer, default=7)
    notify: Mapped[dict] = mapped_column(JSONType, default=lambda: dict(DEFAULT_NOTIFY))
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    unsubscribe_token: Mapped[str] = mapped_column(String(64), default=new_id, unique=True)

    user: Mapped[User] = relationship(back_populates="preferences")


class LearningProfile(Base):
    __tablename__ = "learning_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    background: Mapped[dict] = mapped_column(JSONType, default=dict)
    self_ratings: Mapped[dict] = mapped_column(JSONType, default=dict)
    diagnostic: Mapped[dict] = mapped_column(JSONType, default=dict)
    goals: Mapped[str] = mapped_column(Text, default="")
    onboarding_completed_at: Mapped[datetime | None]
    streak_days: Mapped[int] = mapped_column(Integer, default=0)
    last_study_date: Mapped[date | None] = mapped_column(Date)

    user: Mapped[User] = relationship(back_populates="profile")
