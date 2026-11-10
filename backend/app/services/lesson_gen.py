"""Lesson Generation Service: prepare the next lesson for a student.

prepare_lesson():
  reuse a published version if one exists (shared seed or this student's generated version),
  otherwise run author → validate → (repair) → review → publish, then materialize the assessment
  and notify the student. Idempotent: safe to re-run.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.prompts import author as author_prompt
from app.ai.prompts import reviewer as reviewer_prompt
from app.ai.provider import AIInvalidOutput, get_provider
from app.config import get_settings
from app.db import utcnow
from app.models import (
    Assessment,
    AssessmentQuestion,
    Block,
    EducationalResource,
    Grade,
    GradingRubric,
    LearningProfile,
    Lesson,
    LessonVersion,
    Misconception,
    Module,
    Submission,
    UserLessonProgress,
    UserPreferences,
)
from app.schemas.grading import LessonReview
from app.schemas.lesson import LessonContent
from app.services import mastery
from app.services.audit import audit
from app.services.curriculum import concept_graph, content_hash, lesson_external_prereqs, load_seed_lesson, ordered_lessons
from app.services.lesson_validation import validate_lesson

log = logging.getLogger("academy.lessons")
MAX_AUTHOR_ATTEMPTS = 3
ASSESSMENT_KIND = {"lesson": "lesson", "module_assessment": "module", "block_assessment": "block"}


def published_version(db: Session, user_id: str, lesson_id: str) -> LessonVersion | None:
    """Prefer the student's own generated version, else the shared seed version."""
    for uid in (user_id, None):
        cond = LessonVersion.user_id == uid if uid else LessonVersion.user_id.is_(None)
        v = db.scalars(select(LessonVersion).where(LessonVersion.lesson_id == lesson_id, cond, LessonVersion.purpose == "primary",
                                                   LessonVersion.status == "published").order_by(LessonVersion.version.desc())).first()
        if v:
            return v
    return None


def generation_spec(db: Session, lesson: Lesson) -> dict:
    """The lesson spec, with objectives aggregated from covered lessons for cumulative assessments."""
    spec = dict(lesson.spec)
    if lesson.kind == "lesson":
        return spec
    lessons = [lsn for lsn in ordered_lessons(db) if lsn.kind == "lesson"]
    covers = spec.get("covers") or []
    if covers == "all" or covers == ["all"]:
        covered = [lsn for lsn in lessons if lsn.spec.get("block_key") == spec["block_key"]]
    else:
        covered = [lsn for lsn in lessons if lsn.key in covers]
    spec["objectives"] = [o for lsn in covered for o in lsn.spec.get("objectives", []) if o.get("critical")]
    spec["teaches"] = sorted({c for lsn in covered for c in lsn.spec.get("teaches", [])})
    spec["note"] = "Cumulative assessment: instructions plus question sections only; no new teaching."
    return spec


def demonstrated_concepts(db: Session, user_id: str) -> set[str]:
    passed = db.execute(select(Lesson).join(UserLessonProgress, UserLessonProgress.lesson_id == Lesson.id)
                        .where(UserLessonProgress.user_id == user_id, UserLessonProgress.state == "passed")).scalars().all()
    taught = {c for lsn in passed for c in lsn.spec.get("teaches", [])}
    snap = mastery.concept_snapshot(db, user_id)
    return taught | {k for k, v in snap.items() if v["state"] in mastery.DEMONSTRATED_STATES}


def build_context(db: Session, user_id: str, lesson: Lesson, spec: dict) -> dict:
    graph = concept_graph()
    module = db.get(Module, lesson.module_id)
    block = db.get(Block, module.block_id)
    prereqs = sorted(lesson_external_prereqs(spec, graph) | {a for c in spec.get("teaches", []) for a in graph.ancestors(c)})
    snapshot = mastery.concept_snapshot(db, user_id, prereqs + spec.get("teaches", []))
    misconceptions = [
        {"concept": m.concept_key, "objective": m.objective_key, "description": m.description}
        for m in db.scalars(select(Misconception).where(Misconception.user_id == user_id, Misconception.status == "open").limit(20))
    ]
    recent = db.execute(
        select(Grade, Submission, Assessment).join(Submission, Grade.submission_id == Submission.id)
        .join(Assessment, Submission.assessment_id == Assessment.id).where(Submission.user_id == user_id)
        .order_by(Grade.created_at.desc()).limit(5)
    ).all()
    completed = []
    for prog, lsn in db.execute(select(UserLessonProgress, Lesson).join(Lesson, UserLessonProgress.lesson_id == Lesson.id)
                                .where(UserLessonProgress.user_id == user_id, UserLessonProgress.state == "passed")).all():
        v = db.get(LessonVersion, prog.current_version_id) if prog.current_version_id else None
        completed.append({"key": lsn.key, "title": lsn.title, "summary": (v.content.get("summary") if v else "")})
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user_id))
    prefs = db.scalar(select(UserPreferences).where(UserPreferences.user_id == user_id))
    resources = [{"title": r.title, "url": r.url, "kind": r.kind} for r in
                 db.scalars(select(EducationalResource).where(EducationalResource.verification_status == "verified").limit(40))]
    return {
        "spec": {k: spec[k] for k in ("key", "kind", "title", "teaches", "objectives", "estimated_minutes", "note") if k in spec},
        "position": {"block": block.title, "module": module.title, "lesson_number": lesson.position + 1},
        "prerequisite_mastery": {k: snapshot.get(k, {"state": "not_started"}) | {"name": graph.names.get(k, k)} for k in prereqs},
        "misconceptions": misconceptions,
        "recent_results": [{"assessment": a.title, "score": round(g.score, 2), "passed": g.passed, "critical_failures": g.critical_failures}
                           for g, _, a in recent],
        "completed_lessons": completed,
        "background": {"background": profile.background if profile else {}, "self_ratings": profile.self_ratings if profile else {},
                       "goals": profile.goals if profile else ""},
        "resources": resources,
        "budget_minutes": prefs.daily_goal_minutes if prefs else 60,
        "prerequisites": prereqs,
    }


def _exemplar() -> str:
    data = load_seed_lesson("lessons/b01_m02_l03.yaml").model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False)


def generate_lesson(db: Session, user_id: str, lesson: Lesson) -> LessonVersion:
    settings = get_settings()
    provider = get_provider()
    spec = generation_spec(db, lesson)
    ctx = build_context(db, user_id, lesson, spec)
    allowed = demonstrated_concepts(db, user_id) | set(spec.get("teaches", [])) | set(ctx["prerequisites"])
    previous_prompts = [q["prompt"] for v in db.scalars(select(LessonVersion).where(LessonVersion.user_id.in_([user_id]) | LessonVersion.user_id.is_(None)))
                        for q in v.content.get("questions", [])]
    system = author_prompt.SYSTEM + "\n\nExemplar lesson from this program (match its rigor, not its topic):\n" + _exemplar()
    errors, issues, review_report, report = None, None, {}, None
    for attempt in range(1, MAX_AUTHOR_ATTEMPTS + 1):
        res = provider.structured(
            role="author", system=system, prompt=author_prompt.render(ctx | {"validation_errors": errors, "review_issues": issues}),
            schema=LessonContent, user_id=user_id, context={"lesson": lesson.key, "attempt": attempt, "spec": spec, "prerequisites": ctx["prerequisites"]},
        )
        content = res.value
        report = validate_lesson(content, spec, budget_minutes=ctx["budget_minutes"], allowed_prerequisites=allowed,
                                 previous_prompts=previous_prompts, execute_code=True, check_links=True)
        if report.errors:
            log.warning("lesson %s attempt %d failed validation: %s", lesson.key, attempt, report.errors[:5])
            errors, issues = report.errors, None
            continue
        if settings.ai_lesson_review:
            review = provider.structured(
                role="reviewer", system=reviewer_prompt.SYSTEM,
                prompt=reviewer_prompt.render(content.model_dump(mode="json"), spec, ctx["prerequisite_mastery"]),
                schema=LessonReview, user_id=user_id, context={"lesson": lesson.key, "attempt": attempt},
            ).value
            review_report = review.model_dump()
            if review.verdict == "revise" and attempt < MAX_AUTHOR_ATTEMPTS:
                errors, issues = None, [i.model_dump() for i in review.issues]
                continue
        existing = db.scalars(select(LessonVersion).where(LessonVersion.lesson_id == lesson.id, LessonVersion.user_id == user_id)
                              .order_by(LessonVersion.version.desc())).first()
        data = content.model_dump(mode="json")
        version = LessonVersion(
            lesson_id=lesson.id, user_id=user_id, version=(existing.version + 1 if existing else 1), purpose="primary",
            status="published", source="generated", content=data, content_hash=content_hash(data),
            validation_report=report.as_dict() | {"attempts": attempt}, review_report=review_report, published_at=utcnow(),
        )
        db.add(version)
        db.flush()
        audit(db, "lesson.generated", user_id=user_id, actor="ai", entity_type="lesson_version", entity_id=version.id,
              lesson=lesson.key, attempts=attempt, warnings=report.warnings[:20])
        return version
    raise AIInvalidOutput(f"lesson {lesson.key} failed validation after {MAX_AUTHOR_ATTEMPTS} attempts: {(errors or issues or [])[:5]}")


def rubric_row(db: Session, key: str, criteria: dict) -> GradingRubric:
    h = content_hash(criteria)
    row = db.scalar(select(GradingRubric).where(GradingRubric.key == key, GradingRubric.content_hash == h))
    if row:
        return row
    latest = db.scalars(select(GradingRubric).where(GradingRubric.key == key).order_by(GradingRubric.version.desc())).first()
    row = GradingRubric(key=key, version=(latest.version + 1 if latest else 1), criteria=criteria, content_hash=h)
    db.add(row)
    db.flush()
    return row


def materialize_assessment(db: Session, *, user_id: str, lesson: Lesson, version: LessonVersion, kind: str,
                           threshold: float, questions: list[dict] | None = None, title: str | None = None) -> Assessment:
    content = LessonContent.model_validate(version.content)
    qs = questions if questions is not None else [q.model_dump(mode="json") for q in content.questions]
    a = Assessment(lesson_version_id=version.id, lesson_id=lesson.id, user_id=user_id, kind=kind, title=title or content.title,
                   pass_threshold=threshold, concept_keys=sorted({o.concept_key for o in content.objectives}))
    db.add(a)
    db.flush()
    for i, q in enumerate(qs):
        rubric = q.get("grading", {}).get("rubric")
        rid = rubric_row(db, f"{content.lesson_key}:{q['id']}", rubric).id if rubric else None
        db.add(AssessmentQuestion(
            assessment_id=a.id, question_key=q["id"], position=i, qtype=q["type"], category=q["category"],
            critical=q.get("critical", False), required=q.get("required", True), points=q.get("points", 1.0),
            objective_keys=q["objective_ids"], content=q, rubric_id=rid, content_hash=content_hash(q),
        ))
    db.flush()
    return a


def threshold_for(lesson: Lesson, content: LessonContent | None = None) -> float:
    t = get_settings().thresholds
    if lesson.kind == "module_assessment":
        return t.module
    if lesson.kind == "block_assessment":
        return t.block
    return max(t.lesson, content.completion.pass_threshold) if content else t.lesson


def prepare_lesson(db: Session, user_id: str, lesson_id: str) -> dict:
    from app.services.notifications import notify_lesson_available

    prog = db.scalar(select(UserLessonProgress).where(UserLessonProgress.user_id == user_id, UserLessonProgress.lesson_id == lesson_id))
    if prog is None or prog.state not in ("available", "in_progress"):
        return {"skipped": prog.state if prog else "missing"}
    lesson = db.get(Lesson, lesson_id)
    if prog.current_version_id and prog.active_assessment_id:
        notify_lesson_available(db, user_id, lesson, db.get(LessonVersion, prog.current_version_id))
        return {"already_prepared": True}
    version = published_version(db, user_id, lesson_id) or generate_lesson(db, user_id, lesson)
    content = LessonContent.model_validate(version.content)
    assessment = materialize_assessment(db, user_id=user_id, lesson=lesson, version=version,
                                        kind=ASSESSMENT_KIND[lesson.kind], threshold=threshold_for(lesson, content))
    prog.current_version_id, prog.active_assessment_id = version.id, assessment.id
    audit(db, "lesson.prepared", user_id=user_id, entity_type="lesson", entity_id=lesson.id, version=version.id, source=version.source)
    notify_lesson_available(db, user_id, lesson, version)
    return {"version_id": version.id, "assessment_id": assessment.id}
