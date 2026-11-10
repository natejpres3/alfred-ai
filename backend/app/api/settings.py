from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db import get_db
from app.models import User, UserPreferences
from app.models.identity import DEFAULT_NOTIFY

router = APIRouter(prefix="/api", tags=["settings"])


class PrefsIn(BaseModel):
    timezone: str
    daily_goal_minutes: int = Field(ge=15, le=240)
    delivery_mode: str = Field(pattern="^(immediate|scheduled)$")
    delivery_hour: int = Field(ge=0, le=23)
    email_enabled: bool
    notify: dict[str, bool]
    display_name: str = Field(default="", max_length=120)


def _prefs(db: Session, user: User) -> UserPreferences:
    return db.scalar(select(UserPreferences).where(UserPreferences.user_id == user.id))


@router.get("/settings")
def get_settings_(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _prefs(db, user)
    return {"timezone": p.timezone, "daily_goal_minutes": p.daily_goal_minutes, "delivery_mode": p.delivery_mode,
            "delivery_hour": p.delivery_hour, "email_enabled": p.email_enabled, "notify": DEFAULT_NOTIFY | (p.notify or {}),
            "display_name": user.display_name, "email": user.email}


@router.put("/settings")
def put_settings(body: PrefsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        ZoneInfo(body.timezone)
    except Exception:
        raise HTTPException(422, "Unknown timezone")
    p = _prefs(db, user)
    p.timezone, p.daily_goal_minutes, p.delivery_mode = body.timezone, body.daily_goal_minutes, body.delivery_mode
    p.delivery_hour, p.email_enabled = body.delivery_hour, body.email_enabled
    p.notify = {k: bool(body.notify.get(k, v)) for k, v in DEFAULT_NOTIFY.items()}
    user.display_name = body.display_name
    db.commit()
    return {"ok": True}


@router.get("/email/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    p = db.scalar(select(UserPreferences).where(UserPreferences.unsubscribe_token == token))
    if p is None:
        return HTMLResponse("<p>This unsubscribe link is invalid.</p>", status_code=404)
    p.email_enabled = False
    db.commit()
    return HTMLResponse("<p style='font-family:sans-serif'>You've been unsubscribed from AI Academy emails. "
                        "You can turn emails back on in Settings.</p>")
