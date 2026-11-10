"""Optional onboarding diagnostic: a short objective quiz drawn from Block 1 seed lessons that sets
mastery *priors* and test-out eligibility. Priors never unlock content by themselves."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assessment, AssessmentQuestion, Grade, LearningObjective, LearningProfile, Lesson, RubricResult, UserLessonProgress
from app.services import mastery
from app.services.curriculum import content_hash, load_seed_lesson

ITEMS = {  # lesson seed → question ids (objective items only, so grading is deterministic)
    "lessons/b01_m01_l01.yaml": ["q1", "q4", "q2"],
    "lessons/b01_m01_l02.yaml": ["q1", "q4", "q2"],
    "lessons/b01_m02_l03.yaml": ["q1", "q3", "q5"],
    "lessons/b01_m03_l04.yaml": ["q1", "q3", "q5"],
    "lessons/b01_m03_l05.yaml": ["q2", "q3", "q6"],
}
TEST_OUT_MIN = 1.0  # every diagnostic item for the lesson correct


def create_diagnostic(db: Session, user_id: str) -> Assessment:
    existing = db.scalar(select(Assessment).where(Assessment.user_id == user_id, Assessment.kind == "diagnostic"))
    if existing:
        return existing
    a = Assessment(user_id=user_id, kind="diagnostic", title="Diagnostic: Mathematical Foundations", pass_threshold=0.0)
    db.add(a)
    db.flush()
    pos = 0
    for path, qids in ITEMS.items():
        content = load_seed_lesson(path)
        for qid in qids:
            q = content.question(qid).model_dump(mode="json") | {"required": False, "critical": False}
            key = f"{content.lesson_key}:{qid}"
            db.add(AssessmentQuestion(assessment_id=a.id, question_key=key, position=pos, qtype=q["type"], category=q["category"],
                                      critical=False, required=False, points=1.0, objective_keys=q["objective_ids"],
                                      content=q | {"id": key}, content_hash=content_hash(q)))
            pos += 1
    db.flush()
    return a


def apply_diagnostic(db: Session, user_id: str, grade: Grade) -> dict:
    results = db.scalars(select(RubricResult).where(RubricResult.grade_id == grade.id)).all()
    by_concept: dict[str, list[float]] = {}
    by_lesson: dict[str, list[float]] = {}
    objectives = {o.key: o for o in db.scalars(select(LearningObjective))}
    for r in results:
        frac = r.score / r.max_score if r.max_score else 0.0
        if not (r.details or {}).get("answered"):
            frac = 0.0
        for okey in (r.details or {}).get("objective_ids", []):
            if okey in objectives:
                by_concept.setdefault(objectives[okey].concept_key, []).append(frac)
        by_lesson.setdefault(r.question_key.split(":")[0], []).append(frac)
    priors = {c: sum(v) / len(v) for c, v in by_concept.items()}
    for c, p in priors.items():
        mastery.set_prior(db, user_id, c, p)
    eligible = []
    for lesson in db.scalars(select(Lesson).where(Lesson.key.in_(list(by_lesson)))):
        scores = by_lesson[lesson.key]
        if scores and min(scores) >= TEST_OUT_MIN:
            prog = db.scalar(select(UserLessonProgress).where(UserLessonProgress.user_id == user_id, UserLessonProgress.lesson_id == lesson.id))
            if prog:
                prog.test_out_eligible = True
                eligible.append(lesson.key)
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user_id))
    if profile:
        profile.diagnostic = {"priors": priors, "test_out": eligible, "score": grade.score}
    return {"priors": priors, "test_out": eligible}
