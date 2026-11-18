from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..database import get_db
from ..deps import client_ip, get_human_actor
from ..errors import not_found
from ..models import schemas as S
from ..models.db import TranslationVersion
from ..security import serializers as ser
from ..security.permissions import HumanActor, load_segment, parse_uuid

router = APIRouter(prefix="/v1", tags=["approvals"])


@router.post("/versions/{version_id}/approve", response_model=S.ApproveResponse, status_code=201)
def approve(version_id: str, body: S.ApproveRequest, request: Request, actor: HumanActor = Depends(get_human_actor),
            db: Session = Depends(get_db)):
    """Human-only: needs a signed-in session (cookie) AND a valid CSRF token; see deps.get_human_actor."""
    vid = parse_uuid(version_id, "translation version")
    row = db.execute(select(TranslationVersion).where(TranslationVersion.id == vid)).scalar_one_or_none()
    if row is None:
        raise not_found("translation version")
    seg, member = load_segment(db, actor.user, row.segment_id, ip=client_ip(request), for_update=True)
    ver, _ = services.approve_version(db, actor, seg, member, vid, body.decision, body.comment)
    message = services.APPROVED_MESSAGE if body.decision == "approved" else services.REJECTED_MESSAGE
    return S.ApproveResponse(version=ser.version_out(db, ver), message=message)
