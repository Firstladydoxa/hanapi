from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import schemas as S
from ..models.db import User

router = APIRouter(prefix="/v1", tags=["knowledge"])


@router.get("/tm/search", response_model=S.TMSearchOut)
def tm_search(project_id: str = Query(max_length=64), source_language: str = Query(max_length=16), target_language: str = Query(max_length=16),
              q: str = Query(min_length=1, max_length=5000), min_match: int = Query(70, ge=1, le=100),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..memory import translation_memory as tm
    from ..models.schemas import _norm_lang
    from ..security.permissions import get_membership

    project, _m = get_membership(db, user, project_id)
    results = []
    for m in tm.search(db, project.id, _norm_lang(source_language), _norm_lang(target_language), q, min_match=min_match):
        results.append(S.TMResult(tm_id=str(m.tm_id), source_text=m.source_text, target_text=m.target_text, match_percent=m.match_percent,
                                  match_type=m.match_type, approved_at=m.approved_at,  # type: ignore[arg-type]
                                  provenance={"project_id": str(m.project_id), "version_id": str(m.version_id)}))
    return S.TMSearchOut(results=results)
