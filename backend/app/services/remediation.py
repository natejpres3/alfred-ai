"""Remediation workflow (docs/04 §6): diagnose → plan → mini-lesson with a new strategy →
distinct new questions → remediation assessment."""

from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.prompts import remediation as rem_prompt
from app.ai.provider import AIError, AIInvalidOutput, get_provider
from app.config import get_settings
from app.db import utcnow
from app.models import (
    Assessment,
    AssessmentQuestion,
    Grade,
    LearningObjective,
    Lesson,
    LessonVersion,
    RemediationPlan,
    RubricResult,
    Submission,
    UserLessonProgress,
)
from app.schemas.grading import Diagnosis
from app.schemas.lesson import CompletionCriteria, LessonContent, Question, RemediationContent
from app.services.audit import audit
from app.services.curriculum import concept_graph, content_hash
from app.services.lesson_gen import materialize_assessment, threshold_for
from app.services.lesson_validation import ValidationReport, _check_question, jaccard

DISTINCT_BELOW = 0.6


def failed_objectives(grade: Grade, lesson_objectives: list[str]) -> list[str]:
    t = get_settings().thresholds
    failed = set(grade.critical_failures) | {o for o, s in grade.objective_scores.items() if s < t.critical_objective}
    failed &= set(lesson_objectives) | set(grade.objective_scores)
    if not failed:  # failed on aggregate/category/unanswered: target the weakest objectives
        ranked = sorted(grade.objective_scores.items(), key=lambda kv: kv[1])
        failed = {o for o, s in ranked[:2] if s < 1.0} or {o for o, _ in ranked[:1]}
    return sorted(failed)


def _previous_prompts(db: Session, user_id: str, lesson_id: str) -> dict[str, list[str]]:
    """objective → prompts the student has already seen for this lesson."""
    seen: dict[str, list[str]] = {}
    rows = db.execute(select(AssessmentQuestion).join(Assessment, AssessmentQuestion.assessment_id == Assessment.id)
                      .where(Assessment.lesson_id == lesson_id, Assessment.user_id == user_id)).scalars().all()
    for row in rows:
        for o in row.objective_keys:
            seen.setdefault(o, []).append(row.content["prompt"])
    return seen


def _is_distinct(q: dict, seen: dict[str, list[str]]) -> bool:
    if q["type"] == "code":
        return True  # resubmitting a coding assignment is allowed (revise & resubmit)
    return all(jaccard(q["prompt"], p) < DISTINCT_BELOW for o in q["objective_ids"] for p in seen.get(o, []))


def create_remediation(db: Session, submission_id: str) -> dict:
    existing = db.scalar(select(RemediationPlan).where(RemediationPlan.submission_id == submission_id))
    if existing and existing.status == "ready":
        return {"plan_id": existing.id, "already": True}
    sub = db.get(Submission, submission_id)
    grade = db.scalars(select(Grade).where(Grade.submission_id == sub.id, Grade.superseded_by_id.is_(None)).order_by(Grade.created_at.desc())).first()
    assessment = db.get(Assessment, sub.assessment_id)
    lesson = db.get(Lesson, assessment.lesson_id)
    prog = db.scalar(select(UserLessonProgress).where(UserLessonProgress.user_id == sub.user_id, UserLessonProgress.lesson_id == lesson.id))
    if prog.state != "remediation_required":
        return {"skipped": prog.state}
    version = db.get(LessonVersion, prog.current_version_id)
    content = LessonContent.model_validate(version.content)
    objectives = {o.id: o for o in content.objectives}
    failed = failed_objectives(grade, list(objectives))
    previous_plans = db.scalars(select(RemediationPlan).where(RemediationPlan.user_id == sub.user_id, RemediationPlan.lesson_id == lesson.id)).all()
    attempt = len([p for p in previous_plans if p.submission_id != submission_id]) + 1
    used_strategies = [s for s in [content.explanation_strategy, *[p.strategy for p in previous_plans]] if s]

    # prerequisite fallback: repeated failure on the same objective, or a diagnosed prerequisite gap
    graph = concept_graph()
    repeated = {o for p in previous_plans for o in p.failed_objectives} & set(failed)
    concepts = {objectives[o].concept_key for o in failed if o in objectives}
    prereqs = sorted({r for c in concepts for r in graph.requires.get(c, ())}) if repeated else []

    results = db.scalars(select(RubricResult).where(RubricResult.grade_id == grade.id)).all()
    answers = {a.question_key: a.payload for a in sub.artifacts}
    graded = [{"question": next((q.prompt for q in content.questions if q.id == r.question_key), r.question_key),
               "objectives": (r.details or {}).get("objective_ids", []), "score": f"{r.score:g}/{r.max_score:g}",
               "answer": answers.get(r.question_key), "feedback": r.feedback, "misconceptions": r.misconceptions}
              for r in results if set((r.details or {}).get("objective_ids", [])) & set(failed)]
    failed_detail = [{"id": o, "statement": objectives[o].statement if o in objectives else o,
                      "score": round(grade.objective_scores.get(o, 0.0), 2)} for o in failed]
    provider = get_provider()
    try:
        diagnosis = provider.structured(
            role="remediation", system=rem_prompt.DIAGNOSIS_SYSTEM,
            prompt=rem_prompt.render_diagnosis({"failed_objectives_detail": failed_detail, "graded_answers": graded,
                                                "prerequisite_concepts": sorted({r for c in concepts for r in graph.ancestors(c)})}),
            schema=Diagnosis, user_id=sub.user_id, context={"failed_objectives": failed},
        ).value
        for d in diagnosis.objectives:
            if d.prerequisite_gap and d.prerequisite_gap in graph.requires and d.prerequisite_gap not in prereqs:
                prereqs.append(d.prerequisite_gap)
        diag = diagnosis.model_dump()
    except AIError as e:
        if not getattr(e, "retryable", True):
            raise
        diag = {"objectives": [], "recommended_strategy": "", "error": str(e)}

    seen = _previous_prompts(db, sub.user_id, lesson.id)
    used_variant_ids = {row.question_key for row in db.execute(
        select(AssessmentQuestion).join(Assessment, AssessmentQuestion.assessment_id == Assessment.id)
        .where(Assessment.lesson_id == lesson.id, Assessment.user_id == sub.user_id)).scalars()}
    variants = [q.model_dump(mode="json") for q in content.variant_bank
                if set(q.objective_ids) & set(failed) and q.id not in used_variant_ids]
    code_retries = [q.model_dump(mode="json") for q in content.questions
                    if q.type == "code" and set(q.objective_ids) & set(failed)
                    and grade.objective_scores.get(q.objective_ids[0], 0) < get_settings().thresholds.coding]

    ctx = {
        "failed_objectives_detail": failed_detail, "diagnosis": diag, "prerequisites_to_reteach": [
            {"key": p, "name": graph.names.get(p, p)} for p in prereqs],
        "used_strategies": used_strategies, "previous_questions": [p for ps in seen.values() for p in ps][:40],
        "lesson_summary": content.summary, "attempt": attempt,
        # offline provider inputs
        "failed_objectives": failed, "objective_statements": {o: objectives[o].statement for o in failed if o in objectives},
        "variant_questions": variants, "explanations": [q.grading.explanation for q in content.questions if set(q.objective_ids) & set(failed)][:6],
    }
    rc: RemediationContent | None = None
    new_questions: list[dict] = []
    for _ in range(2):
        rc = provider.structured(role="remediation", system=rem_prompt.CONTENT_SYSTEM, prompt=rem_prompt.render_content(ctx),
                                 schema=RemediationContent, user_id=sub.user_id, context=ctx).value
        report = ValidationReport()
        new_questions = []
        for q in rc.questions:
            _check_question(q, report, f"question {q.id}")
            d = q.model_dump(mode="json")
            if _is_distinct(d, seen) and set(q.objective_ids) <= set(objectives):
                new_questions.append(d)
        covered = {o for q in new_questions for o in q["objective_ids"]}
        if not report.errors and set(failed) <= covered | {o for q in code_retries for o in q["objective_ids"]}:
            break
        ctx["previous_questions"] = ctx["previous_questions"] + [q.prompt for q in rc.questions]
    else:
        if not new_questions:
            raise AIInvalidOutput("remediation produced no valid, distinct questions for the failed objectives")

    # retain one item per *passed* critical objective so passing remediation can't drop earlier mastery
    rng = random.Random(f"{sub.user_id}:{lesson.id}:{attempt}")
    retained: list[dict] = []
    for o in sorted(set(objectives) - set(failed)):
        if not objectives[o].critical:
            continue
        pool = [q for q in content.variant_bank if o in q.objective_ids and q.id not in used_variant_ids] or \
               [q for q in content.questions if o in q.objective_ids and q.type in ("mcq", "numeric")]
        if pool:
            retained.append(rng.choice(pool).model_dump(mode="json"))
    by_id: dict[str, dict] = {}
    for q in new_questions + code_retries + retained:
        by_id.setdefault(q["id"], q)
    questions = list(by_id.values())

    sections = [s.model_dump(mode="json") for s in rc.sections]
    placed = {b.get("question_id") for s in sections for b in s["blocks"] if b["type"] == "question"}
    extra = [q["id"] for q in questions if q["id"] not in placed]
    if extra:
        sections.append({"id": f"rs{attempt}-check", "kind": "recall", "title": "Check your understanding", "estimated_minutes": 8,
                         "required": True, "blocks": [{"type": "question", "question_id": qid} for qid in extra]})
    keep_q = {q["id"] for q in questions}
    for s in sections:
        s["blocks"] = [b for b in s["blocks"] if b["type"] != "question" or b["question_id"] in keep_q]
    sections = [s for s in sections if s["blocks"]]
    rem_content = LessonContent(
        lesson_key=content.lesson_key, title=f"Remediation: {content.title}", subtitle=rc.title, summary=rc.diagnosis_summary,
        why_it_matters=content.why_it_matters, explanation_strategy=rc.strategy,
        objectives=[objectives[o] for o in sorted({o for q in questions for o in q["objective_ids"]}) if o in objectives],
        prerequisites=content.prerequisites, connections=[], estimated_minutes=sum(s["estimated_minutes"] for s in sections),
        sections=sections, questions=[Question.model_validate(q) for q in questions], resources=rc.resources or content.resources,
        completion=CompletionCriteria(required_section_ids=[s["id"] for s in sections], required_question_ids=[q["id"] for q in questions],
                                      pass_threshold=content.completion.pass_threshold),
    )
    data = rem_content.model_dump(mode="json")
    rv = LessonVersion(lesson_id=lesson.id, user_id=sub.user_id, version=1000 + attempt, purpose="remediation", status="published",
                       source="generated", content=data, content_hash=content_hash(data), validation_report={}, published_at=utcnow())
    db.add(rv)
    db.flush()
    rem_assessment = materialize_assessment(db, user_id=sub.user_id, lesson=lesson, version=rv, kind="remediation",
                                            threshold=threshold_for(lesson, content), title=rem_content.title)
    plan = existing or RemediationPlan(user_id=sub.user_id, lesson_id=lesson.id, submission_id=sub.id, attempt=attempt)
    plan.failed_objectives, plan.diagnosis, plan.include_prerequisites = failed, diag, prereqs
    plan.strategy, plan.lesson_version_id, plan.assessment_id, plan.status = rc.strategy, rv.id, rem_assessment.id, "ready"
    db.add(plan)
    prog.active_assessment_id = rem_assessment.id
    db.flush()
    audit(db, "remediation.created", user_id=sub.user_id, actor="ai", entity_type="remediation_plan", entity_id=plan.id,
          failed=failed, prerequisites=prereqs, strategy=rc.strategy, attempt=attempt)
    from app.services.notifications import notify

    notify(db, sub.user_id, "remediation_required", f"remediation:{plan.id}",
           {"lesson_id": lesson.id, "lesson_title": lesson.title, "failed_objectives": [objectives[o].statement for o in failed if o in objectives],
            "prerequisites": [graph.names.get(p, p) for p in prereqs], "summary": grade.summary})
    return {"plan_id": plan.id, "assessment_id": rem_assessment.id, "questions": len(questions)}


def current_remediation(db: Session, user_id: str, lesson_id: str) -> RemediationPlan | None:
    return db.scalars(select(RemediationPlan).where(RemediationPlan.user_id == user_id, RemediationPlan.lesson_id == lesson_id)
                      .order_by(RemediationPlan.created_at.desc())).first()


def objective_statements(db: Session, keys: list[str]) -> dict[str, str]:
    return {o.key: o.statement for o in db.scalars(select(LearningObjective).where(LearningObjective.key.in_(keys)))}
