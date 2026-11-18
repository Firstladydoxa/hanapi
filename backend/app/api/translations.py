from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..database import get_db
from ..deps import client_ip, get_current_user
from ..errors import ApiError
from ..models import schemas as S
from ..models.db import ProjectMember, Segment, User
from ..qa.runner import run_all
from ..security import serializers as ser
from ..security.permissions import get_membership, load_segment, parse_uuid, segment_visible

router = APIRouter(prefix="/v1", tags=["translations"])


@router.get("/translations", response_model=List[S.TranslationListItem])
def list_translations(project_id: str = Query(max_length=64), user: User = Depends(get_current_user), db: Session = Depends(get_db),
                      limit: int = Query(50, ge=1, le=200)):
    project, member = get_membership(db, user, project_id)
    stmt = select(Segment).where(Segment.project_id == project.id, Segment.job_id.is_(None)).order_by(Segment.updated_at.desc()).limit(limit)
    if member.role == "translator":
        stmt = stmt.where(Segment.created_by == user.id)
    return [S.TranslationListItem(translation_id=str(s.id), source_text=s.source_text[:200], target_language=s.target_language,
                                  status=s.status, updated_at=s.updated_at) for s in db.execute(stmt).scalars()]


@router.get("/translations/{translation_id}", response_model=S.TranslationOut)
def get_translation(translation_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    seg, _ = load_segment(db, user, translation_id, ip=client_ip(request))
    return ser.translation_out(db, seg, services.list_versions(db, seg.id))


@router.post("/translations/{translation_id}/versions", response_model=S.NewVersionResponse, status_code=201)
def new_version(translation_id: str, body: S.NewVersionRequest, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    seg, _ = load_segment(db, user, translation_id, ip=client_ip(request), for_update=True)
    ver = services.save_version(db, user, seg, body.target_text, body.parent_version_id, body.change_note)
    warnings = run_all(db, seg.project_id, seg.source_text, ver.target_text, seg.source_language, seg.target_language)
    return S.NewVersionResponse(version=ser.version_out(db, ver), warnings=ser.warnings_out(warnings))


@router.get("/translations/{translation_id}/compare", response_model=S.CompareOut)
def compare(translation_id: str, a: str, b: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..han import tools

    return tools.compare_translations(db, user, translation_id, a, b)
