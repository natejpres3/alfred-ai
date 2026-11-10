"""Password hashing (Argon2id) and opaque server-side session tokens."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import User, UserSession

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(UserSession(user_id=user.id, token_hash=token_hash(token), expires_at=utcnow() + timedelta(days=get_settings().session_days)))
    db.flush()
    return token


def user_for_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    s = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    if s is None or s.revoked_at is not None or s.expires_at < utcnow():
        return None
    return db.get(User, s.user_id)


def revoke(db: Session, token: str) -> None:
    s = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    if s:
        s.revoked_at = utcnow()


class RateLimiter:
    """Small in-process sliding-window limiter (single-instance deployment)."""

    def __init__(self, limit: int, window_s: float):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


login_limiter = RateLimiter(limit=8, window_s=60)
