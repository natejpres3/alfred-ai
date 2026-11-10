"""Application settings. All secrets come from the environment (or a git-ignored .env)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProgressionThresholds(BaseModel):
    """Mastery thresholds as fractions in [0, 1]. See docs/04-curriculum-grading-mastery.md §3."""

    activity_completion: float = 1.0
    lesson: float = 0.85
    conceptual: float = 0.85
    math: float = 0.85
    coding: float = 0.90
    project: float = 0.90
    module: float = 0.85
    block: float = 0.90
    critical_objective: float = 0.85

    def category(self, category: str) -> float:
        return {
            "conceptual": self.conceptual,
            "recall": self.conceptual,
            "math": self.math,
            "coding": self.coding,
        }.get(category, self.lesson)


class RoleModel(BaseModel):
    model: str
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    max_tokens: int


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Academy"
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://academy:academy@localhost:5432/academy"
    public_web_url: str = "http://localhost:3000"
    session_cookie_name: str = "academy_session"
    session_days: int = 30
    cookie_secure: bool = False

    # Thresholds (env: THRESHOLD_LESSON=0.85 …)
    threshold_activity_completion: float = 1.0
    threshold_lesson: float = 0.85
    threshold_conceptual: float = 0.85
    threshold_math: float = 0.85
    threshold_coding: float = 0.90
    threshold_project: float = 0.90
    threshold_module: float = 0.85
    threshold_block: float = 0.90
    threshold_critical_objective: float = 0.85

    # AI
    ai_provider: Literal["anthropic", "fake"] = "anthropic"
    ai_monthly_budget_usd: float = 50.0
    ai_default_model: str = "claude-opus-5-5"
    ai_model_author: str | None = None
    ai_model_reviewer: str | None = None
    ai_model_grader: str | None = None
    ai_model_code_reviewer: str | None = None
    ai_model_tutor: str | None = None
    ai_model_remediation: str | None = None
    ai_model_researcher: str | None = None
    ai_enable_fallbacks: bool = True
    ai_lesson_review: bool = True

    # Sandbox
    sandbox_backend: Literal["docker", "unsafe-local"] = "docker"
    sandbox_image: str = "ai-academy-sandbox:latest"
    sandbox_allow_unsafe_local: bool = False
    sandbox_timeout_seconds: int = 30
    sandbox_memory_mb: int = 512

    # Email
    email_provider: Literal["console", "smtp", "resend"] = "console"
    email_from: str = "AI Academy <academy@localhost>"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    resend_api_key: str | None = None
    outbox_dir: str = "var/outbox"

    # Worker
    worker_poll_seconds: float = 1.0
    worker_id: str = Field(default_factory=lambda: __import__("socket").gethostname())

    @property
    def thresholds(self) -> ProgressionThresholds:
        return ProgressionThresholds(
            activity_completion=self.threshold_activity_completion,
            lesson=self.threshold_lesson,
            conceptual=self.threshold_conceptual,
            math=self.threshold_math,
            coding=self.threshold_coding,
            project=self.threshold_project,
            module=self.threshold_module,
            block=self.threshold_block,
            critical_objective=self.threshold_critical_objective,
        )

    def role(self, role: str) -> RoleModel:
        """Model + effort per AI role. Override the model per role with AI_MODEL_<ROLE>."""
        defaults = {
            "author": ("high", 64000),
            "reviewer": ("high", 16000),
            "grader": ("high", 8000),
            "code_reviewer": ("high", 8000),
            "tutor": ("medium", 8000),
            "remediation": ("high", 48000),
            "researcher": ("medium", 8000),
        }
        effort, max_tokens = defaults[role]
        model = getattr(self, f"ai_model_{role}", None) or self.ai_default_model
        return RoleModel(model=model, effort=effort, max_tokens=max_tokens)


@lru_cache
def get_settings() -> Settings:
    return Settings()
