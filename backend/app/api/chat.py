from __future__ import annotations

from fastapi import APIRouter, Depends

from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user
from ..han import orchestrator
from ..models import schemas as S
from ..models.db import User
from ..ratelimit import enforce

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat", response_model=S.ChatResponse)
def chat(body: S.ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce("translate", str(user.id), get_settings().rate_limit_translate_per_min)
    return orchestrator.handle(db, user, body)
