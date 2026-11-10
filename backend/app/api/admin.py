"""Admin: manual grading review queue, grade overrides, job inspection, AI cost reporting."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import admin_user
from app.config import get_settings
from app.db import get_db, utcnow
from app.models import AICall, Assessment, BackgroundJob, Grade, RubricResult, Submission, User
from app.services import mastery
from app.services.audit import audit
from app.services.workflow import finalize

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/review-queue")
def review_queue(admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Grade, Submission, Assessment).join(Submission, Grade.submission_id == Submission.id)
                      .join(Assessment, Submission.assessment_id == Assessment.id)
                      .where(Grade.needs_review.is_(True), Grade.superseded_by_id.is_(None))).all()
    errored = db.scalars(select(Submission).where(Submission.status == "error")).all()
    out = []
    for g, s, a in rows:
        flagged = db.scalars(select(RubricResult).where(RubricResult.grade_id == g.id, RubricResult.review_status == "flagged")).all()
        out.append({"grade_id": g.id, "submission_id": s.id, "assessment": a.title, "score": g.score,
                    "flagged": [{"question_key": r.question_key, "score": r.score, "max": r.max_score, "criteria": r.criteria} for r in flagged]})
    return {"flagged": out, "errored_submissions": [{"id": s.id, "assessment_id": s.assessment_id} for s in errored]}


class OverrideIn(BaseModel):
    passed: bool
    score: float | None = Field(default=None, ge=0, le=1)
    note: str = Field(min_length=3, max_length=2000)


@router.post("/grades/{grade_id}/override")
def override(grade_id: str, body: OverrideIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    old = db.get(Grade, grade_id)
    if old is None or old.superseded_by_id:
        raise HTTPException(404, "Grade not found or already superseded")
    sub = db.get(Submission, old.submission_id)
    new = Grade(submission_id=sub.id, score=body.score if body.score is not None else old.score, passed=body.passed,
                category_scores=old.category_scores, objective_scores=old.objective_scores,
                critical_failures=[] if body.passed else old.critical_failures, failure_reasons=[] if body.passed else old.failure_reasons,
                summary=f"Manually reviewed: {body.note}", needs_review=False, grader_version=old.grader_version, created_by="admin")
    db.add(new)
    db.flush()
    for r in db.scalars(select(RubricResult).where(RubricResult.grade_id == old.id)):
        db.add(RubricResult(**{c: getattr(r, c) for c in ("question_key", "rubric_id", "grader", "score", "max_score", "criteria", "confidence",
                                                          "correct_concepts", "missing_concepts", "incorrect_claims", "misconceptions",
                                                          "feedback", "next_steps", "meets_mastery", "details", "ai_call_ids")},
                            grade_id=new.id, review_status="overridden" if r.review_status == "flagged" else r.review_status))
    old.superseded_by_id = new.id
    sub.status = "graded"
    db.flush()
    audit(db, "grade.overridden", user_id=sub.user_id, actor="admin", entity_type="grade", entity_id=new.id,
          previous=old.id, passed=body.passed, note=body.note, admin=admin.id)
    a = db.get(Assessment, sub.assessment_id)
    mastery.apply_grade(db, sub.user_id, new, a.kind)
    result = finalize(db, sub, new, a)
    db.commit()
    return {"grade_id": new.id, "result": result}


@router.get("/jobs")
def list_jobs(status: str | None = None, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    q = select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(100)
    if status:
        q = q.where(BackgroundJob.status == status)
    return [{"id": j.id, "kind": j.kind, "status": j.status, "attempts": j.attempts, "last_error": j.last_error,
             "run_at": j.run_at.isoformat(), "payload": j.payload} for j in db.scalars(q)]


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    j = db.get(BackgroundJob, job_id)
    if j is None:
        raise HTTPException(404, "Job not found")
    j.status, j.run_at, j.max_attempts = "queued", utcnow(), max(j.max_attempts, j.attempts + 3)
    db.commit()
    return {"ok": True}


@router.get("/costs")
def costs(admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    month = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    by_role = db.execute(select(AICall.role, AICall.model, func.count(AICall.id), func.sum(AICall.input_tokens),
                                func.sum(AICall.output_tokens), func.sum(AICall.cost_usd))
                         .where(AICall.created_at >= month).group_by(AICall.role, AICall.model)).all()
    errors = db.scalar(select(func.count(AICall.id)).where(AICall.created_at >= month, AICall.status != "ok"))
    total = sum(r[5] or 0 for r in by_role)
    return {"month_start": month.isoformat(), "budget_usd": get_settings().ai_monthly_budget_usd, "spent_usd": round(total, 4),
            "errors": errors, "by_role": [{"role": r[0], "model": r[1], "calls": r[2], "input_tokens": r[3] or 0,
                                           "output_tokens": r[4] or 0, "cost_usd": round(r[5] or 0, 4)} for r in by_role]}
