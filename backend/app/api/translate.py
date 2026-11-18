from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import services
from ..config import get_settings
from ..database import get_db
from ..deps import client_ip, get_current_user
from ..errors import ApiError
from ..models import schemas as S
from ..models.db import User
from ..ratelimit import enforce
from ..security.permissions import get_membership

router = APIRouter(prefix="/v1", tags=["translate"])


@router.post("/translate", response_model=S.TranslateResponse, status_code=201)
def translate(body: S.TranslateRequest, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = get_settings()
    enforce("translate", str(user.id), s.rate_limit_translate_per_min)
    project, _ = get_membership(db, user, body.project_id, ip=client_ip(request))
    if len(body.text) > s.max_text_chars:
        raise ApiError(422, "text_too_long", "This text is too long for a quick translation. Please use the Translation Workspace.")
    if body.context and len(body.context) > s.max_context_chars:
        raise ApiError(422, "context_too_long", "The context note is too long.")
    seg, ver, warnings, matches, terms, note = services.create_draft(
        db, user, project, body.source_language, body.target_language, body.text, context=body.context, domain=body.domain)
    return services.translate_response(seg, ver, warnings, matches, terms, note)
