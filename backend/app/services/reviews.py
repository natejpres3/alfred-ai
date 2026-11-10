"""Spaced retrieval reviews: short quizzes for concepts that are due or at risk."""

from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (
    Assessment,
    AssessmentQuestion,
    Grade,
    Lesson,
    LessonVersion,
    MasteryRecord,
    ReviewSchedule,
    Submission,
    User,
    UserLessonProgress,
)
from app.services import mastery
from app.services.curriculum import concept_graph, content_hash
from app.services.notifications import notify

MAX_CONCEPTS = 3
PER_CONCEPT = 2
REVIEW_TYPES = {"mcq", "multi_select", "numeric", "short_answer"}


def _pool(db: Session, user_id: str, concept: str) -> list[dict]:
    pool = []
    rows = db.execute(select(UserLessonProgress, Lesson).join(Lesson, UserLessonProgress.lesson_id == Lesson.id)
                      .where(UserLessonProgress.user_id == user_id, UserLessonProgress.state == "passed")).all()
    for prog, lesson in rows:
        if concept not in lesson.spec.get("teaches", []) or not prog.current_version_id:
            continue
        v = db.get(LessonVersion, prog.current_version_id)
        objs = {o["id"] for o in v.content["objectives"] if o["concept_key"] == concept}
        for q in v.content.get("variant_bank", []) + v.content["questions"]:
            if q["type"] in REVIEW_TYPES and set(q["objective_ids"]) & objs:
                pool.append(q | {"required": True})
    return pool


def build_review(db: Session, user_id: str, concepts: list[str]) -> Assessment | None:
    graph = concept_graph()
    questions: list[dict] = []
    for c in concepts:
        rec = mastery.record(db, user_id, "concept", c)
        pool = _pool(db, user_id, c)
        rng = random.Random(f"{user_id}:{c}:{rec.evidence_count}:{rec.lapses}")
        rng.shuffle(pool)
        questions += pool[:PER_CONCEPT]
    if not questions:
        return None
    a = Assessment(user_id=user_id, kind="review", title="Review: " + ", ".join(graph.names.get(c, c) for c in concepts),
                   pass_threshold=0.85, concept_keys=concepts)
    db.add(a)
    db.flush()
    seen = set()
    for i, q in enumerate(questions):
        key = q["id"] if q["id"] not in seen else f"{q['id']}-{i}"
        seen.add(key)
        db.add(AssessmentQuestion(assessment_id=a.id, question_key=key, position=i, qtype=q["type"], category=q["category"],
                                  critical=False, required=True, points=q.get("points", 1.0), objective_keys=q["objective_ids"],
                                  content=q | {"id": key}, content_hash=content_hash(q)))
    db.flush()
    return a


def scan_user(db: Session, user_id: str) -> dict:
    due = mastery.refresh_states(db, user_id)
    open_sched = db.scalars(select(ReviewSchedule).where(ReviewSchedule.user_id == user_id, ReviewSchedule.status == "due",
                                                         ReviewSchedule.due_at <= utcnow())).all()
    concepts = sorted({s.concept_key for s in open_sched if s.assessment_id is None} | set(due))[:MAX_CONCEPTS]
    if not concepts:
        return {"due": []}
    if db.scalar(select(Assessment).where(Assessment.user_id == user_id, Assessment.kind == "review")
                 .outerjoin(Submission, Submission.assessment_id == Assessment.id).where(Submission.id.is_(None))):
        return {"due": concepts, "pending_review_exists": True}
    a = build_review(db, user_id, concepts)
    if a is None:
        return {"due": concepts, "no_questions": True}
    for s in open_sched:
        if s.concept_key in concepts:
            s.assessment_id = a.id
    notify(db, user_id, "review_due", f"review_due:{user_id}:{utcnow().date().isoformat()}",
           {"concepts": [concept_graph().names.get(c, c) for c in concepts], "assessment_id": a.id})
    return {"due": concepts, "assessment_id": a.id}


def scan_all(db: Session) -> dict:
    return {u: scan_user(db, u) for u in db.scalars(select(User.id))}


def on_review_graded(db: Session, submission: Submission, grade: Grade) -> None:
    a = db.get(Assessment, submission.assessment_id)
    for s in db.scalars(select(ReviewSchedule).where(ReviewSchedule.user_id == submission.user_id, ReviewSchedule.assessment_id == a.id)):
        s.status, s.completed_at = "completed", utcnow()
    db.flush()


def due_count(db: Session, user_id: str) -> int:
    return len(db.scalars(select(MasteryRecord).where(MasteryRecord.user_id == user_id, MasteryRecord.scope == "concept",
                                                      MasteryRecord.state.in_(["review_due", "at_risk"]))).all())
