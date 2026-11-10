"""Tutor Service: lesson-aware, mode-aware tutoring that never hands out graded solutions."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.prompts import tutor as tutor_prompt
from app.ai.provider import AIError, get_provider
from app.db import SessionLocal, utcnow
from app.models import Assessment, Lesson, LessonVersion, Misconception, Note, TutorConversation, TutorMessage, UserLessonProgress
from app.schemas.lesson import LessonContent
from app.services import mastery

MAX_HISTORY = 30
DISABLED_FOR = {"module", "block", "diagnostic", "review"}


def tutor_available(db: Session, user_id: str, lesson_id: str | None) -> tuple[bool, str]:
    if not lesson_id:
        return True, ""
    prog = db.scalar(select(UserLessonProgress).where(UserLessonProgress.user_id == user_id, UserLessonProgress.lesson_id == lesson_id))
    if prog and prog.active_assessment_id:
        a = db.get(Assessment, prog.active_assessment_id)
        if a and a.kind in DISABLED_FOR and prog.state != "passed":
            return False, "The tutor is disabled during cumulative assessments. It returns once you've submitted."
    return True, ""


def build_system(db: Session, user_id: str, conv: TutorConversation, mode: str) -> str:
    view, concepts, notes = {}, [], ""
    if conv.lesson_id:
        lesson = db.get(Lesson, conv.lesson_id)
        prog = db.scalar(select(UserLessonProgress).where(UserLessonProgress.user_id == user_id, UserLessonProgress.lesson_id == lesson.id))
        if prog and prog.current_version_id:
            view = LessonContent.model_validate(db.get(LessonVersion, prog.current_version_id).content).student_view()
        concepts = lesson.spec.get("teaches", [])
        note = db.scalar(select(Note).where(Note.user_id == user_id, Note.lesson_id == lesson.id))
        notes = note.body if note else ""
    snap = mastery.concept_snapshot(db, user_id)
    mis = [m.description for m in db.scalars(select(Misconception).where(Misconception.user_id == user_id, Misconception.status == "open").limit(10))]
    return (tutor_prompt.SYSTEM + "\n\n" + tutor_prompt.MODES.get(mode, tutor_prompt.MODES["explanation"]) + "\n\n"
            + tutor_prompt.render_context(view, {k: v for k, v in snap.items() if not concepts or k in concepts or v["state"] != "not_started"}, mis, notes))


def stream_reply(user_id: str, conversation_id: str, message: str, mode: str) -> Iterator[str]:
    """Generator used by the SSE endpoint. Owns its own DB session (the request session is closed by then)."""
    db = SessionLocal()
    try:
        conv = db.get(TutorConversation, conversation_id)
        history = [{"role": m.role, "content": m.content} for m in conv.messages][-MAX_HISTORY:]
        db.add(TutorMessage(conversation_id=conv.id, role="user", content=message, mode=mode))
        if not conv.title:
            conv.title = message[:80]
        conv.mode = mode
        system = build_system(db, user_id, conv, mode)
        db.commit()
        chunks: list[str] = []
        try:
            for piece in get_provider().stream_text(role="tutor", system=system, messages=history + [{"role": "user", "content": message}],
                                                    user_id=user_id, context={"conversation": conv.id, "mode": mode}):
                chunks.append(piece)
                yield piece
        except AIError as e:
            msg = f"\n\n_(Tutor unavailable: {e})_"
            chunks.append(msg)
            yield msg
        db.add(TutorMessage(conversation_id=conv.id, role="assistant", content="".join(chunks), mode=mode))
        db.commit()
    finally:
        db.close()


def touch(conv: TutorConversation) -> None:
    conv.created_at = conv.created_at or utcnow()
