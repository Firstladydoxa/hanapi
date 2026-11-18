from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..han import tools
from ..models import schemas as S
from ..models.db import User
from ..models.schemas import _norm_lang
from ..security.permissions import get_membership
from ..terminology import terminology as term_service

router = APIRouter(prefix="/v1", tags=["knowledge"])


@router.get("/terminology/search", response_model=S.TermSearchOut)
def terminology_search(project_id: str = Query(max_length=64), source_language: str = Query(max_length=16),
                       target_language: str = Query(max_length=16), q: str = Query("", max_length=300),
                       domain: Optional[str] = Query(None, max_length=100), user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    project, _m = get_membership(db, user, project_id)
    entries = term_service.search(db, project.id, _norm_lang(source_language), _norm_lang(target_language), q, domain)
    return S.TermSearchOut(results=[tools.term_result(e) for e in entries])
