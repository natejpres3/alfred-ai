from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditEvent


def audit(db: Session, action: str, *, user_id: str | None = None, actor: str = "system",
          entity_type: str = "", entity_id: str | None = None, **data) -> None:
    db.add(AuditEvent(user_id=user_id, actor=actor, action=action, entity_type=entity_type, entity_id=entity_id, data=data))
