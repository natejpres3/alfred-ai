"""Progression Service: the lesson/module state machines, gates, and unlocking (docs/04 §1–2).

All transitions go through `transition()`, which is a no-op when the current state is not one of
`expected_from` — so replays of jobs are harmless — and writes an audit event when it acts.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (
    Assessment,
    Block,
    CodingProject,
    Grade,
    Lesson,
    Module,
    ProjectMilestone,
    ProjectSubmission,
    Submission,
    UserLessonProgress,
    UserModuleProgress,
)
from app.services import jobs, mastery
from app.services.audit import audit
from app.services.curriculum import concept_graph, lesson_external_prereqs, ordered_modules

LESSON_STATES = {"locked", "available", "in_progress", "submitted", "grading", "passed", "remediation_required"}
MODULE_STATES = {"locked", "available", "in_progress", "project_pending", "assessment_pending", "completed"}


def transition(db: Session, prog, to: str, expected_from: set[str], *, reason: str = "", **data) -> bool:
    if prog.state not in expected_from:
        return False
    before = prog.state
    prog.state = to
    now = utcnow()
    if isinstance(prog, UserLessonProgress):
        if to == "available" and prog.unlocked_at is None:
            prog.unlocked_at = now
        if to == "in_progress" and prog.started_at is None:
            prog.started_at = now
        if to == "passed":
            prog.passed_at = now
        entity = "lesson_progress"
    else:
        if to == "completed":
            prog.completed_at = now
        entity = "module_progress"
    audit(db, f"{entity}.transition", user_id=prog.user_id, entity_type=entity, entity_id=prog.id,
          before=before, after=to, reason=reason, **data)
    db.flush()
    return True


def ensure_progress_rows(db: Session, user_id: str) -> None:
    have = set(db.scalars(select(UserLessonProgress.lesson_id).where(UserLessonProgress.user_id == user_id)))
    for lesson_id in db.scalars(select(Lesson.id)):
        if lesson_id not in have:
            db.add(UserLessonProgress(user_id=user_id, lesson_id=lesson_id, state="locked"))
    have_m = set(db.scalars(select(UserModuleProgress.module_id).where(UserModuleProgress.user_id == user_id)))
    for module_id in db.scalars(select(Module.id)):
        if module_id not in have_m:
            db.add(UserModuleProgress(user_id=user_id, module_id=module_id, state="locked"))
    db.flush()


def _progress_maps(db: Session, user_id: str):
    lp = {p.lesson_id: p for p in db.scalars(select(UserLessonProgress).where(UserLessonProgress.user_id == user_id))}
    mp = {p.module_id: p for p in db.scalars(select(UserModuleProgress).where(UserModuleProgress.user_id == user_id))}
    return lp, mp


def project_passed(db: Session, user_id: str, project: CodingProject) -> tuple[bool, float]:
    """Every milestone must have a passing submission; score = mean of best milestone scores."""
    best = []
    for ms in project.milestones:
        scores = db.scalars(select(ProjectSubmission.score).where(ProjectSubmission.user_id == user_id, ProjectSubmission.milestone_id == ms.id,
                                                                   ProjectSubmission.status == "graded")).all()
        best.append(max([s for s in scores if s is not None], default=0.0))
    if not best:
        return True, 1.0
    score = sum(best) / len(best)
    return all(b >= project.pass_threshold for b in best) and score >= project.pass_threshold, score


def refresh(db: Session, user_id: str) -> list[Lesson]:
    """Recompute module completion and unlock everything now eligible. Returns newly available lessons."""
    ensure_progress_rows(db, user_id)
    lp, mp = _progress_maps(db, user_id)
    graph = concept_graph()
    demonstrated = {c for lid, p in lp.items() if p.state == "passed" for c in db.get(Lesson, lid).spec.get("teaches", [])}
    demonstrated |= {k for k, v in mastery.concept_snapshot(db, user_id).items() if v["state"] in mastery.DEMONSTRATED_STATES}
    newly: list[Lesson] = []
    modules = ordered_modules(db)
    module_by_key = {m.key: m for m in modules}
    blocks = db.scalars(select(Block).order_by(Block.position)).all()
    block_unlocked: dict[str, bool] = {}
    prev_block_done = True
    for b in blocks:
        block_unlocked[b.id] = prev_block_done and b.status == "authored"
        block_lessons = [lsn for m in b.modules for lsn in m.lessons]
        prev_block_done = bool(block_lessons) and all(lp[lsn.id].state == "passed" for lsn in block_lessons) and \
            all(mp[m.id].state == "completed" for m in b.modules)

    for m in modules:
        mprog = mp[m.id]
        # --- module completion
        lessons = m.lessons
        if lessons and all(lp[lsn.id].state == "passed" for lsn in lessons):
            project = db.scalar(select(CodingProject).where(CodingProject.module_id == m.id))
            ok = project_passed(db, user_id, project)[0] if project else True
            if ok:
                if transition(db, mprog, "completed", MODULE_STATES - {"completed"}, reason="all lessons and project passed"):
                    _notify_module_completed(db, user_id, m)
            else:
                transition(db, mprog, "project_pending", {"locked", "available", "in_progress", "assessment_pending"}, reason="lessons passed, project pending")
        elif lessons and all(lp[lsn.id].state == "passed" for lsn in lessons if lsn.kind == "lesson"):
            project = db.scalar(select(CodingProject).where(CodingProject.module_id == m.id))
            if project and not project_passed(db, user_id, project)[0]:
                transition(db, mprog, "project_pending", {"locked", "available", "in_progress"}, reason="lessons passed, project pending")
            else:
                transition(db, mprog, "assessment_pending", {"locked", "available", "in_progress"}, reason="module assessment pending")

        # --- module unlock
        reqs = [module_by_key[k] for k in (m.requires_modules or []) if k in module_by_key]
        unlocked = block_unlocked[m.block_id] and all(mp[r.id].state == "completed" for r in reqs)
        if not unlocked:
            continue
        if transition(db, mprog, "available", {"locked"}, reason="prerequisite modules completed"):
            if m.position > 0 or db.get(Block, m.block_id).position > 0:
                _notify_section_unlocked(db, user_id, m)

        # --- lessons in the module (sequential + concept prerequisites)
        prev_passed = True
        for lsn in lessons:
            p = lp[lsn.id]
            if p.state == "locked" and prev_passed and _lesson_eligible(lsn, lessons, lp, graph, demonstrated):
                if transition(db, p, "available", {"locked"}, reason="prerequisites satisfied"):
                    newly.append(lsn)
                    if mprog.state == "available":
                        transition(db, mprog, "in_progress", {"available"})
            prev_passed = p.state == "passed"
    for lsn in newly:
        jobs.enqueue(db, "prepare_lesson", {"user_id": user_id, "lesson_id": lsn.id}, key=f"prepare:{user_id}:{lsn.id}")
    return newly


def _lesson_eligible(lsn: Lesson, module_lessons: list[Lesson], lp, graph, demonstrated: set[str]) -> bool:
    if lsn.kind == "module_assessment":
        return all(lp[x.id].state == "passed" for x in module_lessons if x.kind == "lesson")
    if lsn.kind == "block_assessment":
        return all(lp[x.id].state == "passed" for x in module_lessons if x.id != lsn.id)
    return lesson_external_prereqs(lsn.spec, graph) <= demonstrated


def start_lesson(db: Session, user_id: str, lesson: Lesson) -> None:
    p = db.scalar(select(UserLessonProgress).where(UserLessonProgress.user_id == user_id, UserLessonProgress.lesson_id == lesson.id))
    if transition(db, p, "in_progress", {"available"}, reason="opened"):
        mastery.mark_introduced(db, user_id, lesson.spec.get("teaches", []))


def on_submitted(db: Session, submission: Submission) -> None:
    a = db.get(Assessment, submission.assessment_id)
    if a.lesson_id is None:
        return
    p = db.scalar(select(UserLessonProgress).where(UserLessonProgress.user_id == submission.user_id, UserLessonProgress.lesson_id == a.lesson_id))
    if p and transition(db, p, "submitted", {"available", "in_progress", "remediation_required"}, reason="submitted", submission=submission.id):
        p.attempts += 1


def on_grading_started(db: Session, submission: Submission) -> None:
    a = db.get(Assessment, submission.assessment_id)
    if a.lesson_id is None:
        return
    p = db.scalar(select(UserLessonProgress).where(UserLessonProgress.user_id == submission.user_id, UserLessonProgress.lesson_id == a.lesson_id))
    if p:
        transition(db, p, "grading", {"submitted"}, reason="grading started", submission=submission.id)


def on_graded(db: Session, submission: Submission, grade: Grade) -> dict:
    """Apply a final grade to progression. Idempotent."""
    from app.services import notifications

    a = db.get(Assessment, submission.assessment_id)
    if a.kind in ("review", "diagnostic") or a.lesson_id is None:
        return {"kind": a.kind}
    lesson = db.get(Lesson, a.lesson_id)
    p = db.scalar(select(UserLessonProgress).where(UserLessonProgress.user_id == submission.user_id, UserLessonProgress.lesson_id == lesson.id))
    if grade.needs_review:
        notifications.notify(db, submission.user_id, "submission_graded", f"graded:{submission.id}",
                             {"lesson_id": lesson.id, "lesson_title": lesson.title, "submission_id": submission.id, "score": grade.score,
                              "passed": False, "needs_review": True, "summary": grade.summary})
        return {"needs_review": True}
    p.best_score = max(p.best_score or 0.0, grade.score)
    if grade.passed:
        if transition(db, p, "passed", {"grading", "submitted"}, reason="assessment passed", grade=grade.id, score=grade.score):
            notifications.notify(db, submission.user_id, "lesson_passed", f"passed:{submission.user_id}:{lesson.id}",
                                 {"lesson_id": lesson.id, "lesson_title": lesson.title, "submission_id": submission.id,
                                  "score": grade.score, "summary": grade.summary})
        unlocked = refresh(db, submission.user_id)
        return {"passed": True, "unlocked": [x.key for x in unlocked]}
    if transition(db, p, "remediation_required", {"grading", "submitted"}, reason="assessment failed", grade=grade.id,
                  critical_failures=grade.critical_failures):
        jobs.enqueue(db, "create_remediation", {"submission_id": submission.id}, key=f"remediation:{submission.id}")
        notifications.notify(db, submission.user_id, "submission_graded", f"graded:{submission.id}",
                             {"lesson_id": lesson.id, "lesson_title": lesson.title, "submission_id": submission.id, "score": grade.score,
                              "passed": False, "summary": grade.summary})
    return {"passed": False}


def on_project_graded(db: Session, user_id: str, milestone: ProjectMilestone) -> list[Lesson]:
    return refresh(db, user_id)


def _notify_module_completed(db: Session, user_id: str, module: Module) -> None:
    from app.services import notifications

    notifications.notify(db, user_id, "module_completed", f"module_completed:{user_id}:{module.id}",
                         {"module_id": module.id, "module_title": module.title})


def _notify_section_unlocked(db: Session, user_id: str, module: Module) -> None:
    from app.services import notifications

    notifications.notify(db, user_id, "section_unlocked", f"section_unlocked:{user_id}:{module.id}",
                         {"module_id": module.id, "module_title": module.title})
