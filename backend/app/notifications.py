"""Create in-app notifications. Callers commit; a failure here must never break the workflow that raised it."""
from __future__ import annotations

import logging
import uuid
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models.db import Notification, User
from .security.permissions import ADMIN_ROLES

log = logging.getLogger("han.notifications")


def notify(db: Session, user_ids: Iterable[uuid.UUID], kind: str, title: str, body: Optional[str] = None,
           link: Optional[str] = None, level: str = "info", exclude: Optional[uuid.UUID] = None) -> int:
    ids = {u for u in user_ids if u and u != exclude}
    try:
        with db.begin_nested():
            for uid in ids:
                db.add(Notification(user_id=uid, kind=kind, title=title[:200], body=(body or "")[:1000] or None, link=link, level=level))
        db.commit()
    except Exception:  # noqa: BLE001
        log.exception("notification_failed kind=%s", kind)
        db.rollback()
        return 0
    return len(ids)


def admin_ids(db: Session) -> list[uuid.UUID]:
    return list(db.execute(select(User.id).where(User.role.in_(ADMIN_ROLES), User.status == "active")).scalars())
