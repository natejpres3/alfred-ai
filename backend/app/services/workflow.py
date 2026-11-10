"""Background job handlers: the glue between grading, mastery, progression and notifications."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assessment, Grade, Submission
from app.services import diagnostic, grading, lesson_gen, mastery, notifications, progression, projects, remediation, reviews
from app.services.audit import audit
from app.services.jobs import handler


@handler("grade_submission")
def job_grade_submission(db: Session, payload: dict) -> dict:
    sub = db.get(Submission, payload["submission_id"])
    existing = db.scalars(select(Grade).where(Grade.submission_id == sub.id, Grade.superseded_by_id.is_(None))).first()
    a = db.get(Assessment, sub.assessment_id)
    if existing is None:
        progression.on_grading_started(db, sub)
        sub.status = "grading"
        grade = grading.grade_submission(db, sub)
        audit(db, "submission.graded", user_id=sub.user_id, entity_type="grade", entity_id=grade.id, score=grade.score,
              passed=grade.passed, needs_review=grade.needs_review, grader_version=grade.grader_version)
        if a.kind == "diagnostic":
            return diagnostic.apply_diagnostic(db, sub.user_id, grade)
        if not grade.needs_review:
            mastery.apply_grade(db, sub.user_id, grade, a.kind)
    else:
        grade = existing
    return finalize(db, sub, grade, a)


def finalize(db: Session, sub: Submission, grade: Grade, a: Assessment) -> dict:
    if a.kind == "review":
        reviews.on_review_graded(db, sub, grade)
        return {"review": True, "score": grade.score}
    if a.kind == "diagnostic":
        return {"diagnostic": True}
    return progression.on_graded(db, sub, grade)


@handler("grade_submission:dead")
def job_grade_dead(db: Session, payload: dict) -> None:
    sub = db.get(Submission, payload["submission_id"])
    if sub:
        sub.status = "error"
        audit(db, "submission.grading_failed", user_id=sub.user_id, entity_type="submission", entity_id=sub.id, error=payload.get("error"))


@handler("prepare_lesson")
def job_prepare_lesson(db: Session, payload: dict) -> dict:
    return lesson_gen.prepare_lesson(db, payload["user_id"], payload["lesson_id"])


@handler("create_remediation")
def job_create_remediation(db: Session, payload: dict) -> dict:
    return remediation.create_remediation(db, payload["submission_id"])


@handler("send_notification")
def job_send_notification(db: Session, payload: dict) -> dict:
    return notifications.send_notification(db, payload["notification_id"])


@handler("send_notification:dead")
def job_send_dead(db: Session, payload: dict) -> None:
    notifications.mark_failed(db, payload)


@handler("grade_project")
def job_grade_project(db: Session, payload: dict) -> dict:
    return projects.grade(db, payload["project_submission_id"])


@handler("scan_reviews")
def job_scan_reviews(db: Session, payload: dict) -> dict:
    return reviews.scan_all(db)


@handler("refresh_unlocks")
def job_refresh(db: Session, payload: dict) -> dict:
    return {"unlocked": [lsn.key for lsn in progression.refresh(db, payload["user_id"])]}
