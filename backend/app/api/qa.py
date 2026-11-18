from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import schemas as S
from ..models.db import User
from ..qa.runner import run_all
from ..security import serializers as ser
from ..security.permissions import get_membership

router = APIRouter(prefix="/v1", tags=["qa"])


@router.post("/qa/check", response_model=S.QAOut)
def qa_check(body: S.QARequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, _m = get_membership(db, user, body.project_id)
    warnings = run_all(db, project.id, body.source_text, body.target_text, body.source_language, body.target_language)
    return S.QAOut(warnings=ser.warnings_out(warnings))
