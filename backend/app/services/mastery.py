"""Mastery Service: evidence → objective/concept estimates, concept states, misconceptions, and
spaced-repetition scheduling (docs/04 §5)."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Grade, LearningObjective, MasteryRecord, Misconception, ReviewSchedule, RubricResult

MASTERED = 0.85
REMEDIATION_BELOW = 0.6
AT_RISK_RETRIEVABILITY = 0.6
ALPHA_FLOOR = 0.35
INITIAL_STABILITY_DAYS = 2.0
MAX_STABILITY_DAYS = 180.0
DEMONSTRATED_STATES = {"mastered", "review_due", "at_risk"}

QUESTION_WEIGHT = {"code": 1.5, "derivation": 1.5, "long_answer": 1.2, "short_answer": 1.2, "mcq": 1.0, "multi_select": 1.0, "numeric": 1.0}
CONTEXT_WEIGHT = {"lesson": 1.0, "remediation": 1.0, "module": 1.0, "block": 1.0, "review": 0.7, "diagnostic": 0.5}


def record(db: Session, user_id: str, scope: str, key: str) -> MasteryRecord:
    rec = db.scalar(select(MasteryRecord).where(MasteryRecord.user_id == user_id, MasteryRecord.scope == scope, MasteryRecord.key == key))
    if rec is None:
        rec = MasteryRecord(user_id=user_id, scope=scope, key=key, estimate=0.0, evidence_weight=0.0, evidence_count=0,
                            state="not_started", stability_days=0.0, lapses=0)
        db.add(rec)
        db.flush()
    return rec


def update_estimate(rec: MasteryRecord, score: float, weight: float, now: datetime) -> None:
    if rec.evidence_count == 0 and rec.prior is not None:
        rec.estimate = rec.prior
        rec.evidence_weight = 0.5  # a prior counts as half an observation
    alpha = max(ALPHA_FLOOR, weight / (rec.evidence_weight + weight)) if rec.evidence_count or rec.prior is not None else 1.0
    rec.estimate = rec.estimate + alpha * (score - rec.estimate)
    rec.evidence_weight += weight
    rec.evidence_count += 1
    rec.last_score = score
    rec.last_evidence_at = now


def retrievability(rec: MasteryRecord, now: datetime) -> float:
    if not rec.mastered_at or rec.stability_days <= 0:
        return 1.0
    anchor = rec.last_evidence_at or rec.mastered_at
    return math.exp(-max(0.0, (now - anchor).total_seconds() / 86400) / rec.stability_days)


def objective_evidence(results: list[RubricResult], context_weight: float) -> dict[str, tuple[float, float]]:
    """objective → (weighted mean score fraction, total weight)."""
    acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in results:
        d = r.details or {}
        if not d.get("required", True) and not d.get("answered", True):
            continue
        w = QUESTION_WEIGHT.get(d.get("qtype", ""), 1.0) * context_weight
        frac = r.score / r.max_score if r.max_score else 0.0
        for o in d.get("objective_ids", []):
            acc[o][0] += frac * w
            acc[o][1] += w
    return {o: (s / w, w) for o, (s, w) in acc.items() if w > 0}


def apply_grade(db: Session, user_id: str, grade: Grade, assessment_kind: str) -> dict[str, str]:
    """Update objective and concept mastery from a grade. Returns concept → new state."""
    now = utcnow()
    results = db.scalars(select(RubricResult).where(RubricResult.grade_id == grade.id)).all()
    evidence = objective_evidence(list(results), CONTEXT_WEIGHT.get(assessment_kind, 1.0))
    objectives = {o.key: o for o in db.scalars(select(LearningObjective).where(LearningObjective.key.in_(list(evidence))))}
    touched_concepts: set[str] = set()
    for okey, (score, weight) in evidence.items():
        update_estimate(record(db, user_id, "objective", okey), score, weight, now)
        if okey in objectives:
            touched_concepts.add(objectives[okey].concept_key)

    # misconceptions: open from failing answers, resolve on mastery
    for r in results:
        frac = r.score / r.max_score if r.max_score else 0.0
        for okey in (r.details or {}).get("objective_ids", []):
            concept = objectives[okey].concept_key if okey in objectives else ""
            if frac < MASTERED and r.misconceptions:
                for m in r.misconceptions[:3]:
                    db.add(Misconception(user_id=user_id, concept_key=concept, objective_key=okey, description=m,
                                         source_rubric_result_id=r.id, status="open"))
            elif frac >= MASTERED:
                for mc in db.scalars(select(Misconception).where(Misconception.user_id == user_id, Misconception.objective_key == okey,
                                                                 Misconception.status == "open")):
                    mc.status, mc.resolved_at = "resolved", now
    db.flush()

    current: dict[str, float] = {}
    for okey, (score, _) in evidence.items():
        if okey in objectives:
            c = objectives[okey].concept_key
            current[c] = min(current.get(c, 1.0), score)
    states = {}
    for concept in touched_concepts:
        states[concept] = recompute_concept(db, user_id, concept, grade_passed=grade.passed, review=(assessment_kind == "review"),
                                            now=now, current_score=current.get(concept))
    return states


def recompute_concept(db: Session, user_id: str, concept: str, *, grade_passed: bool, review: bool, now: datetime,
                      current_score: float | None = None) -> str:
    """`current_score` is the weakest objective score for this concept in the grade being applied. A passing
    assessment in which every objective of the concept clears the bar demonstrates mastery, even if the
    long-run estimate is still catching up after earlier failures."""
    obj_keys = db.scalars(select(LearningObjective.key).where(LearningObjective.concept_key == concept)).all()
    recs = db.scalars(select(MasteryRecord).where(MasteryRecord.user_id == user_id, MasteryRecord.scope == "objective",
                                                  MasteryRecord.key.in_(obj_keys), MasteryRecord.evidence_count > 0)).all()
    c = record(db, user_id, "concept", concept)
    if not recs:
        return c.state
    total_w = sum(r.evidence_weight for r in recs)
    c.estimate = sum(r.estimate * r.evidence_weight for r in recs) / total_w
    c.evidence_count += 1
    latest = max(recs, key=lambda r: r.last_evidence_at or now)
    c.last_score, c.last_evidence_at = latest.last_score, now
    was_demonstrated = c.state in DEMONSTRATED_STATES or c.mastered_at is not None

    if review and was_demonstrated:
        s = c.last_score or 0.0
        if s >= MASTERED:
            c.stability_days = min(MAX_STABILITY_DAYS, c.stability_days * (1.8 + 0.6 * (s - MASTERED) / (1 - MASTERED)))
            c.state = "mastered"
        elif s >= REMEDIATION_BELOW:
            c.stability_days = min(MAX_STABILITY_DAYS, c.stability_days * 1.2)
            c.state = "mastered"
        else:
            c.lapses += 1
            c.stability_days = max(1.0, c.stability_days * 0.3)
            c.state = "needs_remediation"
        c.next_review_at = now + timedelta(days=c.stability_days)
    elif grade_passed and (c.estimate >= MASTERED or (current_score is not None and current_score >= MASTERED)):
        if not was_demonstrated:
            c.mastered_at = now
            c.stability_days = INITIAL_STABILITY_DAYS
        c.state = "mastered"
        c.next_review_at = now + timedelta(days=max(c.stability_days, INITIAL_STABILITY_DAYS))
    elif (c.last_score or 0) < REMEDIATION_BELOW:
        c.state = "needs_remediation"
    elif not was_demonstrated:
        c.state = "practiced"
    if c.next_review_at and c.state in DEMONSTRATED_STATES | {"needs_remediation"}:
        _ensure_review(db, user_id, concept, c.next_review_at)
    db.flush()
    return c.state


def _ensure_review(db: Session, user_id: str, concept: str, due: datetime) -> None:
    pending = db.scalar(select(ReviewSchedule).where(ReviewSchedule.user_id == user_id, ReviewSchedule.concept_key == concept,
                                                     ReviewSchedule.status == "due"))
    if pending:
        pending.due_at = due
    else:
        db.add(ReviewSchedule(user_id=user_id, concept_key=concept, due_at=due, status="due"))


def refresh_states(db: Session, user_id: str, now: datetime | None = None) -> list[str]:
    """Move mastered concepts to review_due / at_risk as time passes. Returns concepts now due."""
    now = now or utcnow()
    due = []
    for c in db.scalars(select(MasteryRecord).where(MasteryRecord.user_id == user_id, MasteryRecord.scope == "concept",
                                                    MasteryRecord.state.in_(list(DEMONSTRATED_STATES)))):
        if retrievability(c, now) < AT_RISK_RETRIEVABILITY:
            c.state = "at_risk"
        elif c.next_review_at and now >= c.next_review_at:
            c.state = "review_due"
        if c.state in ("review_due", "at_risk"):
            due.append(c.key)
    db.flush()
    return due


def mark_introduced(db: Session, user_id: str, concepts: list[str]) -> None:
    for k in concepts:
        rec = record(db, user_id, "concept", k)
        if rec.state == "not_started":
            rec.state = "introduced"


def set_prior(db: Session, user_id: str, concept: str, prior: float) -> None:
    rec = record(db, user_id, "concept", concept)
    rec.prior = max(0.0, min(1.0, prior))
    for key in db.scalars(select(LearningObjective.key).where(LearningObjective.concept_key == concept)):
        record(db, user_id, "objective", key).prior = rec.prior


def concept_snapshot(db: Session, user_id: str, keys: list[str] | None = None) -> dict[str, dict]:
    q = select(MasteryRecord).where(MasteryRecord.user_id == user_id, MasteryRecord.scope == "concept")
    if keys is not None:
        q = q.where(MasteryRecord.key.in_(keys))
    return {r.key: {"estimate": round(r.estimate, 3), "state": r.state, "evidence": r.evidence_count, "prior": r.prior}
            for r in db.scalars(q)}
