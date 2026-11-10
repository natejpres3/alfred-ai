from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType


class LessonVersion(Base):
    """Immutable once published. `user_id` is NULL for shared seed content."""

    __tablename__ = "lesson_versions"

    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(16), default="primary")  # primary|remediation|review
    status: Mapped[str] = mapped_column(String(16), default="draft")
    source: Mapped[str] = mapped_column(String(16), default="seed")  # seed|generated
    content: Mapped[dict] = mapped_column(JSONType)
    content_hash: Mapped[str] = mapped_column(String(64))
    validation_report: Mapped[dict] = mapped_column(JSONType, default=dict)
    review_report: Mapped[dict] = mapped_column(JSONType, default=dict)
    published_at: Mapped[datetime | None]


class EducationalResource(Base):
    __tablename__ = "educational_resources"

    url: Mapped[str] = mapped_column(String(1000), unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(400))
    authors: Mapped[list] = mapped_column(JSONType, default=list)
    publisher: Mapped[str] = mapped_column(String(200), default="")
    verification_status: Mapped[str] = mapped_column(String(16), default="unverified")
    http_status: Mapped[int | None] = mapped_column(Integer)
    checked_at: Mapped[datetime | None]
    resource_metadata: Mapped[dict] = mapped_column("metadata", JSONType, default=dict)


class GradingRubric(Base):
    __tablename__ = "grading_rubrics"
    __table_args__ = (UniqueConstraint("key", "version"),)

    key: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    criteria: Mapped[dict] = mapped_column(JSONType)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)


class Assessment(Base):
    __tablename__ = "assessments"

    lesson_version_id: Mapped[str | None] = mapped_column(ForeignKey("lesson_versions.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # lesson|remediation|module|block|review|diagnostic
    title: Mapped[str] = mapped_column(String(300))
    pass_threshold: Mapped[float] = mapped_column(Float)
    concept_keys: Mapped[list] = mapped_column(JSONType, default=list)

    questions: Mapped[list[AssessmentQuestion]] = relationship(
        back_populates="assessment", order_by="AssessmentQuestion.position"
    )


class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"
    __table_args__ = (UniqueConstraint("assessment_id", "question_key"),)

    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"), index=True)
    question_key: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer)
    qtype: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(16))
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    points: Mapped[float] = mapped_column(Float, default=1.0)
    objective_keys: Mapped[list] = mapped_column(JSONType, default=list)
    content: Mapped[dict] = mapped_column(JSONType)  # full Question incl. grading spec
    rubric_id: Mapped[str | None] = mapped_column(ForeignKey("grading_rubrics.id"))
    content_hash: Mapped[str] = mapped_column(String(64))

    assessment: Mapped[Assessment] = relationship(back_populates="questions")


class UserLessonProgress(Base):
    __tablename__ = "user_lesson_progress"
    __table_args__ = (UniqueConstraint("user_id", "lesson_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), index=True)
    state: Mapped[str] = mapped_column(String(24), default="locked")
    current_version_id: Mapped[str | None] = mapped_column(ForeignKey("lesson_versions.id"))
    active_assessment_id: Mapped[str | None] = mapped_column(ForeignKey("assessments.id"))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    test_out_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    unlocked_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    passed_at: Mapped[datetime | None]
    best_score: Mapped[float | None] = mapped_column(Float)


class UserModuleProgress(Base):
    __tablename__ = "user_module_progress"
    __table_args__ = (UniqueConstraint("user_id", "module_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"))
    state: Mapped[str] = mapped_column(String(24), default="locked")
    lessons_passed_at: Mapped[datetime | None]
    assessment_passed_at: Mapped[datetime | None]
    project_passed_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]


class LessonActivity(Base):
    __tablename__ = "lesson_activities"
    __table_args__ = (UniqueConstraint("user_id", "lesson_version_id", "section_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_version_id: Mapped[str] = mapped_column(ForeignKey("lesson_versions.id"))
    section_id: Mapped[str] = mapped_column(String(80))
    completed_at: Mapped[datetime]


class LearningSession(Base):
    __tablename__ = "learning_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"))
    started_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    active_seconds: Mapped[int] = mapped_column(Integer, default=0)


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (UniqueConstraint("user_id", "lesson_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"))
    body: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime | None]


class TutorConversation(Base):
    __tablename__ = "tutor_conversations"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"))
    mode: Mapped[str] = mapped_column(String(16), default="explanation")
    title: Mapped[str] = mapped_column(String(200), default="")

    messages: Mapped[list[TutorMessage]] = relationship(order_by="TutorMessage.created_at")


class TutorMessage(Base):
    __tablename__ = "tutor_messages"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("tutor_conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user|assistant
    content: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16), default="explanation")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="submitted")
    idempotency_key: Mapped[str] = mapped_column(String(80))
    submitted_at: Mapped[datetime]
    graded_at: Mapped[datetime | None]
    test_out: Mapped[bool] = mapped_column(Boolean, default=False)

    artifacts: Mapped[list[SubmissionArtifact]] = relationship()


class SubmissionArtifact(Base):
    __tablename__ = "submission_artifacts"

    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), index=True)
    question_key: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSONType)
    storage_key: Mapped[str | None] = mapped_column(String(400))


class Grade(Base):
    __tablename__ = "grades"

    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    passed: Mapped[bool] = mapped_column(Boolean)
    category_scores: Mapped[dict] = mapped_column(JSONType, default=dict)
    objective_scores: Mapped[dict] = mapped_column(JSONType, default=dict)
    critical_failures: Mapped[list] = mapped_column(JSONType, default=list)
    failure_reasons: Mapped[list] = mapped_column(JSONType, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    grader_version: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[str] = mapped_column(String(16), default="system")
    superseded_by_id: Mapped[str | None] = mapped_column(ForeignKey("grades.id"))

    rubric_results: Mapped[list[RubricResult]] = relationship()


class RubricResult(Base):
    __tablename__ = "rubric_results"

    grade_id: Mapped[str] = mapped_column(ForeignKey("grades.id"), index=True)
    question_key: Mapped[str] = mapped_column(String(120))
    rubric_id: Mapped[str | None] = mapped_column(ForeignKey("grading_rubrics.id"))
    grader: Mapped[str] = mapped_column(String(16))  # deterministic|rubric_llm|code
    score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float)
    criteria: Mapped[list] = mapped_column(JSONType, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    correct_concepts: Mapped[list] = mapped_column(JSONType, default=list)
    missing_concepts: Mapped[list] = mapped_column(JSONType, default=list)
    incorrect_claims: Mapped[list] = mapped_column(JSONType, default=list)
    misconceptions: Mapped[list] = mapped_column(JSONType, default=list)
    feedback: Mapped[str] = mapped_column(Text, default="")
    next_steps: Mapped[list] = mapped_column(JSONType, default=list)
    meets_mastery: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(16), default="auto")
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    ai_call_ids: Mapped[list] = mapped_column(JSONType, default=list)


class MasteryRecord(Base):
    __tablename__ = "mastery_records"
    __table_args__ = (UniqueConstraint("user_id", "scope", "key"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(10))  # concept|objective
    key: Mapped[str] = mapped_column(String(80))
    estimate: Mapped[float] = mapped_column(Float, default=0.0)
    prior: Mapped[float | None] = mapped_column(Float)
    evidence_weight: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(20), default="not_started")
    stability_days: Mapped[float] = mapped_column(Float, default=0.0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    last_evidence_at: Mapped[datetime | None]
    mastered_at: Mapped[datetime | None]
    next_review_at: Mapped[datetime | None]
    last_score: Mapped[float | None] = mapped_column(Float)


class Misconception(Base):
    __tablename__ = "misconceptions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    concept_key: Mapped[str] = mapped_column(String(64))
    objective_key: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open")
    source_rubric_result_id: Mapped[str | None] = mapped_column(ForeignKey("rubric_results.id"))
    resolved_at: Mapped[datetime | None]


class RemediationPlan(Base):
    __tablename__ = "remediation_plans"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"))
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), unique=True)
    attempt: Mapped[int] = mapped_column(Integer)
    failed_objectives: Mapped[list] = mapped_column(JSONType, default=list)
    diagnosis: Mapped[dict] = mapped_column(JSONType, default=dict)
    include_prerequisites: Mapped[list] = mapped_column(JSONType, default=list)
    strategy: Mapped[str] = mapped_column(String(40), default="")
    lesson_version_id: Mapped[str | None] = mapped_column(ForeignKey("lesson_versions.id"))
    assessment_id: Mapped[str | None] = mapped_column(ForeignKey("assessments.id"))
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|ready|completed|failed


class ReviewSchedule(Base):
    __tablename__ = "review_schedules"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    concept_key: Mapped[str] = mapped_column(String(64))
    due_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(12), default="due")  # due|completed|skipped
    assessment_id: Mapped[str | None] = mapped_column(ForeignKey("assessments.id"))
    completed_at: Mapped[datetime | None]


class ProjectSubmission(Base):
    __tablename__ = "project_submissions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    milestone_id: Mapped[str] = mapped_column(ForeignKey("project_milestones.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(12), default="editor")  # editor|github|upload
    code: Mapped[str] = mapped_column(Text, default="")
    repo_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(12), default="submitted")
    test_results: Mapped[dict] = mapped_column(JSONType, default=dict)
    review: Mapped[dict] = mapped_column(JSONType, default=dict)
    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    feedback: Mapped[str] = mapped_column(Text, default="")
