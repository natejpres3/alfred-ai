from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.ai.prompts.tutor import MODES
from app.api.deps import current_user
from app.db import get_db
from app.models import TutorConversation, User, UserLessonProgress
from app.services import tutor

router = APIRouter(prefix="/api/tutor", tags=["tutor"])
MODE_PATTERN = "^(" + "|".join(MODES) + ")$"


class ConversationIn(BaseModel):
    lesson_id: str | None = None
    mode: str = Field(default="explanation", pattern=MODE_PATTERN)


@router.post("/conversations")
def create_conversation(body: ConversationIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.lesson_id:
        p = db.scalar(select(UserLessonProgress).where(UserLessonProgress.user_id == user.id, UserLessonProgress.lesson_id == body.lesson_id))
        if p is None or p.state == "locked":
            raise HTTPException(403, "Lesson not available")
    conv = TutorConversation(user_id=user.id, lesson_id=body.lesson_id, mode=body.mode)
    db.add(conv)
    db.commit()
    return {"id": conv.id}


@router.get("/conversations")
def list_conversations(lesson_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(TutorConversation).where(TutorConversation.user_id == user.id)
    if lesson_id:
        q = q.where(TutorConversation.lesson_id == lesson_id)
    convs = db.scalars(q.order_by(TutorConversation.created_at.desc()).limit(20)).all()
    return [{"id": c.id, "title": c.title, "mode": c.mode, "lesson_id": c.lesson_id, "created_at": c.created_at.isoformat(),
             "messages": [{"role": m.role, "content": m.content, "mode": m.mode} for m in c.messages]} for c in convs]


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    mode: str = Field(default="explanation", pattern=MODE_PATTERN)


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conv = db.get(TutorConversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    ok, reason = tutor.tutor_available(db, user.id, conv.lesson_id)
    if not ok:
        raise HTTPException(403, reason)

    def events():
        for piece in tutor.stream_reply(user.id, conv.id, body.message, body.mode):
            yield {"event": "delta", "data": json.dumps({"text": piece})}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(events())
