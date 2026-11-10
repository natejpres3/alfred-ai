"""Student-facing learning API: onboarding, dashboard, roadmap, lessons, assessments, submissions, reviews."""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import get_settings
from app.db import get_db, utcnow
from app.models import (
    Assessment,
    AuditEvent,
    Block,
    CodingProject,
    Grade,
    LearningProfile,
    LearningSession,
    Lesson,
    LessonActivity,
    LessonVersion,
    MasteryRecord,
    Module,
    Note,
    Notification,
    RubricResult,
    Submission,
    SubmissionArtifact,
    User,
    UserLessonProgress,
    UserModuleProgress,
    UserPreferences,
)
from app.schemas.lesson import LessonContent
from app.services import diagnostic, jobs, progression, remediation, reviews
from app.services.audit import audit
from app.services.curriculum import concept_graph, lesson_external_prereqs, load_spec, ordered_lessons
from app.services.projects import project_status

router = APIRouter(prefix="/api", tags=["learning"])


# ------------------------------------------------------------------ helpers


def _progress(db: Session, user_id: str, lesson_id: str) -> UserLessonProgress:
    p = db.scalar(select(UserLessonProgress).where(UserLessonProgress.user_id == user_id, UserLessonProgress.lesson_id == lesson_id))
    if p is None:
        raise HTTPException(404, "Lesson not found")
    return p


def _touch_streak(db: Session, user: User) -> None:
    prefs = db.scalar(select(UserPreferences).where(UserPreferences.user_id == user.id))
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user.id))
    today = utcnow().astimezone(ZoneInfo(prefs.timezone if prefs else "UTC")).date()
    if profile.last_study_date == today:
        return
    profile.streak_days = profile.streak_days + 1 if profile.last_study_date == today - timedelta(days=1) else 1
    profile.last_study_date = today


def student_question(content: dict) -> dict:
    q = dict(content)
    q.pop("grading", None)
    return q


def latest_grade(db: Session, submission_id: str) -> Grade | None:
    return db.scalars(select(Grade).where(Grade.submission_id == submission_id, Grade.superseded_by_id.is_(None))
                      .order_by(Grade.created_at.desc())).first()


def _lesson_path(db: Session, lesson: Lesson) -> dict:
    m = db.get(Module, lesson.module_id)
    b = db.get(Block, m.block_id)
    return {"block": {"key": b.key, "title": b.title, "position": b.position}, "module": {"id": m.id, "key": m.key, "title": m.title, "position": m.position}}


# ------------------------------------------------------------------ onboarding


class BackgroundIn(BaseModel):
    math: int = Field(ge=0, le=4)
    programming: int = Field(ge=0, le=4)
    ml: int = Field(ge=0, le=4)
    ai: int = Field(ge=0, le=4)
    notes: str = Field(default="", max_length=4000)


class ProfileIn(BaseModel):
    background: BackgroundIn
    goals: str = Field(default="", max_length=4000)
    daily_goal_minutes: int = Field(default=60, ge=15, le=240)
    timezone: str = "UTC"
    delivery_mode: str = Field(default="immediate", pattern="^(immediate|scheduled)$")
    delivery_hour: int = Field(default=7, ge=0, le=23)
    email_enabled: bool = True


@router.get("/onboarding")
def onboarding_overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    spec = load_spec()
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user.id))
    diag = db.scalar(select(Assessment).where(Assessment.user_id == user.id, Assessment.kind == "diagnostic"))
    return {
        "program": {"title": spec["title"], "blocks": [
            {"key": b["key"], "title": b["title"], "status": b.get("status", "outline"),
             "topics": b.get("topics") or [m["title"] for m in b.get("modules", [])]} for b in spec["blocks"]]},
        "profile": {"background": profile.background, "goals": profile.goals, "completed": bool(profile.onboarding_completed_at),
                    "diagnostic": profile.diagnostic},
        "diagnostic_assessment_id": diag.id if diag else None,
    }


@router.post("/onboarding/profile")
def save_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        ZoneInfo(body.timezone)
    except Exception:
        raise HTTPException(422, "Unknown timezone")
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user.id))
    prefs = db.scalar(select(UserPreferences).where(UserPreferences.user_id == user.id))
    profile.background = body.background.model_dump()
    profile.self_ratings = {k: v for k, v in body.background.model_dump().items() if k != "notes"}
    profile.goals = body.goals
    prefs.daily_goal_minutes, prefs.timezone = body.daily_goal_minutes, body.timezone
    prefs.delivery_mode, prefs.delivery_hour, prefs.email_enabled = body.delivery_mode, body.delivery_hour, body.email_enabled
    progression.ensure_progress_rows(db, user.id)
    db.commit()
    return {"ok": True}


@router.post("/onboarding/diagnostic")
def start_diagnostic(user: User = Depends(current_user), db: Session = Depends(get_db)):
    progression.ensure_progress_rows(db, user.id)
    a = diagnostic.create_diagnostic(db, user.id)
    db.commit()
    return {"assessment_id": a.id}


@router.post("/onboarding/complete")
def complete_onboarding(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user.id))
    if profile.onboarding_completed_at is None:
        profile.onboarding_completed_at = utcnow()
        audit(db, "onboarding.completed", user_id=user.id, actor="user", entity_type="user", entity_id=user.id)
    unlocked = progression.refresh(db, user.id)
    db.commit()
    return {"unlocked": [{"id": x.id, "title": x.title} for x in unlocked]}


# ------------------------------------------------------------------ dashboard & roadmap


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    progs = {p.lesson_id: p for p in db.scalars(select(UserLessonProgress).where(UserLessonProgress.user_id == user.id))}
    lessons = ordered_lessons(db)
    current = next((lsn for lsn in lessons if progs.get(lsn.id) and progs[lsn.id].state in
                    ("in_progress", "remediation_required", "submitted", "grading", "available")), None)
    authored = [lsn for lsn in lessons]
    passed = [lsn for lsn in authored if progs.get(lsn.id) and progs[lsn.id].state == "passed"]
    spec = load_spec()
    outline_topics = sum(len(b.get("topics", [])) for b in spec["blocks"] if b.get("status") == "outline")
    remaining_min = sum(lsn.spec.get("estimated_minutes", 60) for lsn in authored if lsn not in passed)
    recent = db.execute(
        select(Grade, Submission, Assessment).join(Submission, Grade.submission_id == Submission.id)
        .join(Assessment, Submission.assessment_id == Assessment.id)
        .where(Submission.user_id == user.id, Grade.superseded_by_id.is_(None)).order_by(Grade.created_at.desc()).limit(6)
    ).all()
    graph = concept_graph()
    concepts = db.scalars(select(MasteryRecord).where(MasteryRecord.user_id == user.id, MasteryRecord.scope == "concept")).all()
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user.id))
    prefs = db.scalar(select(UserPreferences).where(UserPreferences.user_id == user.id))
    projects = []
    for proj in db.scalars(select(CodingProject)):
        mp = db.scalar(select(UserModuleProgress).where(UserModuleProgress.user_id == user.id, UserModuleProgress.module_id == proj.module_id))
        if mp and mp.state != "locked":
            st = project_status(db, user.id, proj)
            projects.append({"key": proj.key, "title": proj.title, "passed": st["passed"], "score": st["score"],
                             "milestones_passed": sum(m["passed"] for m in st["milestones"]), "milestones_total": len(st["milestones"])})
    history = db.scalars(select(AuditEvent).where(AuditEvent.user_id == user.id, AuditEvent.action.in_(
        ["lesson_progress.transition", "submission.graded", "remediation.created", "project.submitted"]))
        .order_by(AuditEvent.created_at.desc()).limit(12)).all()
    lesson_titles = {lsn.id: lsn.title for lsn in lessons}
    today_minutes = db.scalar(select(func.coalesce(func.sum(LearningSession.active_seconds), 0)).where(
        LearningSession.user_id == user.id, LearningSession.started_at >= utcnow() - timedelta(hours=24))) or 0
    return {
        "user": {"display_name": user.display_name, "email_verified": user.email_verified_at is not None},
        "onboarded": bool(profile.onboarding_completed_at),
        "current": ({"lesson_id": current.id, "title": current.title, "state": progs[current.id].state, "kind": current.kind,
                     "prepared": bool(progs[current.id].active_assessment_id), **_lesson_path(db, current),
                     "estimated_minutes": current.spec.get("estimated_minutes", 60)} if current else None),
        "progress": {"lessons_passed": len(passed), "lessons_total": len(authored),
                     "blocks_total": len(spec["blocks"]), "outline_topics_remaining": outline_topics,
                     "percent_known": round(len(passed) / max(1, len(authored)) * 100, 1)},
        "workload": {"remaining_specified_hours": round(remaining_min / 60, 1), "remaining_outline_hours_estimate": outline_topics,
                     "daily_goal_minutes": prefs.daily_goal_minutes, "studied_last_24h_minutes": round(today_minutes / 60)},
        "streak_days": profile.streak_days,
        "recent_grades": [{"submission_id": s.id, "title": a.title, "kind": a.kind, "score": g.score, "passed": g.passed,
                           "needs_review": g.needs_review, "at": g.created_at.isoformat()} for g, s, a in recent],
        "mastered": [{"key": c.key, "name": graph.names.get(c.key, c.key), "estimate": c.estimate} for c in concepts if c.state == "mastered"],
        "needs_review": [{"key": c.key, "name": graph.names.get(c.key, c.key), "state": c.state, "estimate": c.estimate}
                         for c in concepts if c.state in ("review_due", "at_risk", "needs_remediation")],
        "reviews_due": reviews.due_count(db, user.id),
        "available": [{"lesson_id": lsn.id, "title": lsn.title, "state": progs[lsn.id].state} for lsn in lessons
                      if progs.get(lsn.id) and progs[lsn.id].state in ("available", "in_progress", "remediation_required")],
        "projects": projects,
        "history": [{"at": e.created_at.isoformat(), "action": e.action, "data": e.data,
                     "lesson": lesson_titles.get(e.data.get("lesson_id", "")) if isinstance(e.data, dict) else None} for e in history],
        "notifications": [{"kind": n.kind, "payload": n.payload, "status": n.status, "at": n.created_at.isoformat()} for n in
                          db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.kind != "verify_email")
                                     .order_by(Notification.created_at.desc()).limit(5))],
    }


@router.get("/curriculum")
def roadmap(user: User = Depends(current_user), db: Session = Depends(get_db)):
    progs = {p.lesson_id: p for p in db.scalars(select(UserLessonProgress).where(UserLessonProgress.user_id == user.id))}
    mprogs = {p.module_id: p for p in db.scalars(select(UserModuleProgress).where(UserModuleProgress.user_id == user.id))}
    projects = {p.module_id: p for p in db.scalars(select(CodingProject))}
    out = []
    for b in db.scalars(select(Block).order_by(Block.position)):
        modules = []
        for m in b.modules:
            proj = projects.get(m.id)
            modules.append({
                "id": m.id, "key": m.key, "title": m.title, "description": m.description,
                "state": mprogs[m.id].state if m.id in mprogs else "locked",
                "project": ({"key": proj.key, "title": proj.title} if proj else None),
                "lessons": [{"id": lsn.id, "key": lsn.key, "title": lsn.title, "kind": lsn.kind,
                             "state": progs[lsn.id].state if lsn.id in progs else "locked",
                             "estimated_minutes": lsn.spec.get("estimated_minutes", 60), "authored": bool(lsn.seed_path),
                             "best_score": progs[lsn.id].best_score if lsn.id in progs else None} for lsn in m.lessons],
            })
        out.append({"key": b.key, "title": b.title, "description": b.description, "status": b.status, "topics": b.topics, "modules": modules})
    return {"blocks": out}


# ------------------------------------------------------------------ lessons


@router.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(404, "Lesson not found")
    p = _progress(db, user.id, lesson_id)
    base = {"id": lesson.id, "key": lesson.key, "title": lesson.title, "kind": lesson.kind, "state": p.state,
            **_lesson_path(db, lesson), "test_out_eligible": p.test_out_eligible, "attempts": p.attempts, "best_score": p.best_score}
    if p.state == "locked":
        graph = concept_graph()
        need = lesson_external_prereqs(lesson.spec, graph)
        return base | {"locked_reason": "Complete the earlier lessons in this module first."
                       + (f" Requires: {', '.join(graph.names.get(c, c) for c in sorted(need))}." if need else "")}
    if not p.current_version_id:
        return base | {"preparing": True}
    version = db.get(LessonVersion, p.current_version_id)
    content = LessonContent.model_validate(version.content)
    done = set(db.scalars(select(LessonActivity.section_id).where(LessonActivity.user_id == user.id, LessonActivity.lesson_version_id == version.id)))
    note = db.scalar(select(Note).where(Note.user_id == user.id, Note.lesson_id == lesson.id))
    active = db.get(Assessment, p.active_assessment_id) if p.active_assessment_id else None
    rem = None
    if active and active.kind == "remediation":
        rv = db.get(LessonVersion, active.lesson_version_id)
        rc = LessonContent.model_validate(rv.content)
        rdone = set(db.scalars(select(LessonActivity.section_id).where(LessonActivity.user_id == user.id, LessonActivity.lesson_version_id == rv.id)))
        plan = remediation.current_remediation(db, user.id, lesson.id)
        rem = {"version_id": rv.id, "content": rc.student_view(), "completed_sections": sorted(rdone),
               "failed_objectives": plan.failed_objectives if plan else [], "prerequisites": plan.include_prerequisites if plan else []}
    elif p.state == "remediation_required":
        rem = {"preparing": True}
    subs = db.scalars(select(Submission).join(Assessment, Submission.assessment_id == Assessment.id)
                      .where(Submission.user_id == user.id, Assessment.lesson_id == lesson.id).order_by(Submission.submitted_at.desc())).all()
    history = []
    for s in subs:
        g = latest_grade(db, s.id)
        history.append({"submission_id": s.id, "attempt": s.attempt, "status": s.status, "submitted_at": s.submitted_at.isoformat(),
                        "score": g.score if g else None, "passed": g.passed if g else None})
    from app.services.tutor import tutor_available

    tutor_ok, tutor_reason = tutor_available(db, user.id, lesson.id)
    return base | {
        "version_id": version.id, "source": version.source, "content": content.student_view(), "completed_sections": sorted(done),
        "note": note.body if note else "", "assessment": ({"id": active.id, "kind": active.kind, "threshold": active.pass_threshold} if active else None),
        "remediation": rem, "submissions": history, "tutor": {"available": tutor_ok, "reason": tutor_reason},
    }


@router.post("/lessons/{lesson_id}/start")
def start(lesson_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lesson = db.get(Lesson, lesson_id)
    p = _progress(db, user.id, lesson_id)
    if p.state == "locked":
        raise HTTPException(403, "Lesson is locked")
    progression.start_lesson(db, user.id, lesson)
    now = utcnow()
    session = LearningSession(user_id=user.id, lesson_id=lesson_id, started_at=now, last_seen_at=now)
    db.add(session)
    _touch_streak(db, user)
    db.commit()
    return {"state": p.state, "session_id": session.id}


class SectionIn(BaseModel):
    version_id: str


@router.post("/lessons/{lesson_id}/sections/{section_id}/complete")
def complete_section(lesson_id: str, section_id: str, body: SectionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _progress(db, user.id, lesson_id)
    v = db.get(LessonVersion, body.version_id)
    if v is None or v.lesson_id != lesson_id or (v.user_id not in (None, user.id)):
        raise HTTPException(404, "Version not found")
    if section_id not in {s["id"] for s in v.content["sections"]}:
        raise HTTPException(404, "Section not found")
    if p.state == "locked":
        raise HTTPException(403, "Lesson is locked")
    exists = db.scalar(select(LessonActivity).where(LessonActivity.user_id == user.id, LessonActivity.lesson_version_id == v.id,
                                                    LessonActivity.section_id == section_id))
    if not exists:
        db.add(LessonActivity(user_id=user.id, lesson_version_id=v.id, section_id=section_id, completed_at=utcnow()))
        _touch_streak(db, user)
    db.commit()
    return {"ok": True}


class HeartbeatIn(BaseModel):
    session_id: str
    seconds: int = Field(ge=0, le=300)


@router.post("/lessons/{lesson_id}/heartbeat")
def heartbeat(lesson_id: str, body: HeartbeatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(LearningSession, body.session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "Session not found")
    s.active_seconds += body.seconds
    s.last_seen_at = utcnow()
    db.commit()
    return {"active_seconds": s.active_seconds}


class NoteIn(BaseModel):
    body: str = Field(max_length=50_000)


@router.put("/lessons/{lesson_id}/note")
def save_note(lesson_id: str, body: NoteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _progress(db, user.id, lesson_id)
    note = db.scalar(select(Note).where(Note.user_id == user.id, Note.lesson_id == lesson_id))
    if note is None:
        note = Note(user_id=user.id, lesson_id=lesson_id)
        db.add(note)
    note.body, note.updated_at = body.body, utcnow()
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ assessments & submissions


def _assessment_for(db: Session, user: User, assessment_id: str) -> Assessment:
    a = db.get(Assessment, assessment_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(404, "Assessment not found")
    return a


@router.get("/assessments/{assessment_id}")
def get_assessment(assessment_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = _assessment_for(db, user, assessment_id)
    subs = db.scalars(select(Submission).where(Submission.assessment_id == a.id).order_by(Submission.submitted_at.desc())).all()
    return {"id": a.id, "kind": a.kind, "title": a.title, "threshold": a.pass_threshold, "lesson_id": a.lesson_id,
            "questions": [student_question(q.content) for q in a.questions],
            "submissions": [{"id": s.id, "status": s.status, "attempt": s.attempt} for s in subs]}


class SubmissionIn(BaseModel):
    answers: dict[str, dict]
    idempotency_key: str = Field(min_length=8, max_length=80)
    test_out: bool = False


@router.post("/assessments/{assessment_id}/submissions")
def submit(assessment_id: str, body: SubmissionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = _assessment_for(db, user, assessment_id)
    dup = db.scalar(select(Submission).where(Submission.user_id == user.id, Submission.idempotency_key == body.idempotency_key))
    if dup:
        return {"submission_id": dup.id, "status": dup.status, "duplicate": True}
    question_keys = {q.question_key for q in a.questions}
    unknown = set(body.answers) - question_keys
    if unknown:
        raise HTTPException(422, f"Unknown questions: {sorted(unknown)}")
    for k, payload in body.answers.items():
        if len(str(payload)) > 100_000:
            raise HTTPException(413, f"Answer to {k} is too large")
    if a.lesson_id and a.kind not in ("review", "diagnostic"):
        p = _progress(db, user.id, a.lesson_id)
        if p.active_assessment_id != a.id:
            raise HTTPException(409, "This assessment is no longer active for the lesson")
        allowed = {"available", "in_progress"} if a.kind != "remediation" else {"remediation_required"}
        if p.state not in allowed:
            raise HTTPException(409, f"Cannot submit while the lesson is '{p.state}'")
        version = db.get(LessonVersion, a.lesson_version_id)
        required = set(version.content["completion"]["required_section_ids"])
        done = set(db.scalars(select(LessonActivity.section_id).where(LessonActivity.user_id == user.id, LessonActivity.lesson_version_id == version.id)))
        if body.test_out and not p.test_out_eligible:
            raise HTTPException(403, "Test-out is not available for this lesson")
        threshold = get_settings().thresholds.activity_completion
        completion = len(required & done) / max(1, len(required))
        if not body.test_out and completion < threshold:
            raise HTTPException(422, {"message": "Complete every required section before submitting.",
                                      "missing_sections": sorted(required - done)})
    elif db.scalar(select(Submission).where(Submission.assessment_id == a.id)):
        raise HTTPException(409, "This assessment has already been submitted")
    attempt = (db.scalar(select(func.count(Submission.id)).where(Submission.assessment_id == a.id, Submission.user_id == user.id)) or 0) + 1
    sub = Submission(user_id=user.id, assessment_id=a.id, attempt=attempt, status="submitted", idempotency_key=body.idempotency_key,
                     submitted_at=utcnow(), test_out=body.test_out)
    db.add(sub)
    db.flush()
    kinds = {row.question_key: row.qtype for row in a.questions}
    for k, payload in body.answers.items():
        kind = {"mcq": "choice", "multi_select": "choice", "numeric": "numeric", "code": "code"}.get(kinds[k], "text")
        db.add(SubmissionArtifact(submission_id=sub.id, question_key=k, kind=kind, payload=payload))
    progression.on_submitted(db, sub)
    jobs.enqueue(db, "grade_submission", {"submission_id": sub.id}, key=f"grade:{sub.id}")
    audit(db, "submission.created", user_id=user.id, actor="user", entity_type="submission", entity_id=sub.id,
          assessment=a.id, kind=a.kind, lesson_id=a.lesson_id, attempt=attempt)
    _touch_streak(db, user)
    db.commit()
    return {"submission_id": sub.id, "status": sub.status}


@router.get("/submissions/{submission_id}")
def get_submission(submission_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sub = db.get(Submission, submission_id)
    if sub is None or sub.user_id != user.id:
        raise HTTPException(404, "Submission not found")
    a = db.get(Assessment, sub.assessment_id)
    g = latest_grade(db, sub.id)
    answers = {x.question_key: x.payload for x in sub.artifacts}
    out = {"id": sub.id, "status": sub.status, "attempt": sub.attempt, "submitted_at": sub.submitted_at.isoformat(),
           "assessment": {"id": a.id, "kind": a.kind, "title": a.title, "threshold": a.pass_threshold, "lesson_id": a.lesson_id}, "grade": None}
    if g is None:
        return out
    results = {r.question_key: r for r in db.scalars(select(RubricResult).where(RubricResult.grade_id == g.id))}
    questions = []
    for row in a.questions:
        r = results.get(row.question_key)
        q = row.content
        item = {"key": row.question_key, "type": row.qtype, "category": row.category, "critical": row.critical, "required": row.required,
                "prompt": q["prompt"], "options": q.get("options"), "answer": answers.get(row.question_key)}
        if r:
            details = dict(r.details or {})
            item |= {"score": r.score, "max_score": r.max_score, "feedback": r.feedback, "criteria": r.criteria,
                     "correct_concepts": r.correct_concepts, "missing_concepts": r.missing_concepts, "incorrect_claims": r.incorrect_claims,
                     "misconceptions": r.misconceptions, "next_steps": r.next_steps, "meets_mastery": r.meets_mastery,
                     "confidence": r.confidence, "review_status": r.review_status, "grader": r.grader,
                     "explanation": details.get("reference_explanation") or q.get("grading", {}).get("explanation"),
                     "offline_grader": details.get("offline_grader", False),
                     "tests": (details.get("tests") or {}) if r.grader == "code" else None,
                     "static_violations": details.get("static_violations", []),
                     "correct_option_ids": q.get("grading", {}).get("correct_option_ids") if row.qtype in ("mcq", "multi_select") else None}
        questions.append(item)
    out["grade"] = {"id": g.id, "score": g.score, "passed": g.passed, "needs_review": g.needs_review, "summary": g.summary,
                    "category_scores": g.category_scores, "objective_scores": g.objective_scores,
                    "objective_statements": remediation.objective_statements(db, list(g.objective_scores)),
                    "critical_failures": g.critical_failures, "failure_reasons": g.failure_reasons,
                    "grader_version": g.grader_version, "created_by": g.created_by, "questions": questions}
    return out


# ------------------------------------------------------------------ reviews & notifications


@router.get("/reviews")
def get_reviews(user: User = Depends(current_user), db: Session = Depends(get_db)):
    pending = db.scalars(select(Assessment).where(Assessment.user_id == user.id, Assessment.kind == "review")
                         .outerjoin(Submission, Submission.assessment_id == Assessment.id).where(Submission.id.is_(None))).first()
    graph = concept_graph()
    due = db.scalars(select(MasteryRecord).where(MasteryRecord.user_id == user.id, MasteryRecord.scope == "concept",
                                                 MasteryRecord.state.in_(["review_due", "at_risk"]))).all()
    upcoming = db.scalars(select(MasteryRecord).where(MasteryRecord.user_id == user.id, MasteryRecord.scope == "concept",
                                                      MasteryRecord.next_review_at.is_not(None)).order_by(MasteryRecord.next_review_at)).all()
    return {"pending_assessment_id": pending.id if pending else None,
            "due": [{"key": c.key, "name": graph.names.get(c.key, c.key), "state": c.state} for c in due],
            "upcoming": [{"key": c.key, "name": graph.names.get(c.key, c.key), "next_review_at": c.next_review_at.isoformat(),
                          "stability_days": round(c.stability_days, 1), "state": c.state} for c in upcoming]}


@router.post("/reviews/start")
def start_review(user: User = Depends(current_user), db: Session = Depends(get_db)):
    res = reviews.scan_user(db, user.id)
    db.commit()
    if res.get("assessment_id"):
        return {"assessment_id": res["assessment_id"]}
    pending = db.scalars(select(Assessment).where(Assessment.user_id == user.id, Assessment.kind == "review")
                         .outerjoin(Submission, Submission.assessment_id == Assessment.id).where(Submission.id.is_(None))).first()
    if pending:
        return {"assessment_id": pending.id}
    raise HTTPException(404, "Nothing is due for review right now")


@router.get("/notifications")
def list_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(50))
    return [{"id": n.id, "kind": n.kind, "payload": {k: v for k, v in n.payload.items() if k != "token"}, "status": n.status,
             "at": n.created_at.isoformat()} for n in rows]

