from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..errors import not_found
from ..models.db import Notification, User
from ..security.permissions import parse_uuid

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


def _out(n: Notification) -> dict:
    return {"id": str(n.id), "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
            "level": n.level, "read": n.read_at is not None, "created_at": n.created_at}


@router.get("")
def list_notifications(unread_only: bool = False, limit: int = 40, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = db.execute(q.order_by(Notification.created_at.desc()).limit(max(1, min(limit, 100)))).scalars().all()
    unread = db.execute(select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))).scalar_one()
    return {"unread": unread, "items": [_out(n) for n in rows]}


@router.post("/read-all")
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=func.now()))
    db.commit()
    return {"unread": 0}


@router.post("/{notification_id}/read")
def mark_read(notification_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, parse_uuid(notification_id, "notification"))
    if n is None or n.user_id != user.id:
        raise not_found("notification")
    if n.read_at is None:
        n.read_at = func.now()
        db.commit()
        db.refresh(n)
    return _out(n)
