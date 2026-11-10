from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import get_settings
from app.db import get_db, utcnow
from app.models import EmailVerificationToken, LearningProfile, User, UserPreferences
from app.security import create_session, hash_password, login_limiter, revoke, token_hash, verify_password
from app.services.notifications import notify

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


def _set_cookie(resp: Response, token: str) -> None:
    s = get_settings()
    resp.set_cookie(s.session_cookie_name, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                    max_age=s.session_days * 86400, path="/")


def me_payload(db: Session, user: User) -> dict:
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user.id))
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "is_admin": user.is_admin,
            "email_verified": user.email_verified_at is not None,
            "onboarded": bool(profile and profile.onboarding_completed_at)}


@router.post("/register")
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    first = (db.scalar(select(func.count(User.id))) or 0) == 0
    user = User(email=email, password_hash=hash_password(body.password), display_name=body.display_name, is_admin=first)
    db.add(user)
    db.flush()
    db.add(UserPreferences(user_id=user.id))
    db.add(LearningProfile(user_id=user.id))
    token = secrets.token_urlsafe(24)
    db.add(EmailVerificationToken(user_id=user.id, token_hash=token_hash(token), expires_at=utcnow() + timedelta(days=3)))
    db.flush()
    notify(db, user.id, "verify_email", f"verify_email:{user.id}", {"token": token})
    _set_cookie(response, create_session(db, user))
    db.commit()
    return me_payload(db, user)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else '?'}:{body.email.lower()}"
    if not login_limiter.allow(key):
        raise HTTPException(429, "Too many attempts; wait a minute")
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    _set_cookie(response, create_session(db, user))
    db.commit()
    return me_payload(db, user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(get_settings().session_cookie_name)
    if token:
        revoke(db, token)
        db.commit()
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return me_payload(db, user)


class VerifyIn(BaseModel):
    token: str


@router.post("/verify-email")
def verify_email(body: VerifyIn, db: Session = Depends(get_db)):
    row = db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash(body.token)))
    if row is None or row.used_at or row.expires_at < utcnow():
        raise HTTPException(400, "This link is invalid or has expired")
    row.used_at = utcnow()
    db.get(User, row.user_id).email_verified_at = utcnow()
    db.commit()
    return {"ok": True}
