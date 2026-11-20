"""Persistent HAN conversations. A translator only ever reaches their own conversations; admins get no special read access."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..deps import client_ip, get_current_user
from ..han import conversations as conv_svc
from ..han import orchestrator
from ..models import schemas as S
from ..models.db import Project, User
from ..ratelimit import enforce
from ..security.permissions import get_membership

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


def _out(db: Session, conv) -> S.ConversationOut:
    names = {}
    if conv.project_id:
        p = db.get(Project, conv.project_id)
        names = {p.id: p.name} if p else {}
    return conv_svc.conversation_out(db, conv, names)


@router.post("", response_model=S.ConversationDetail, status_code=201)
def create(body: S.ConversationCreate, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_membership(db, user, body.project_id)[0] if body.project_id else None
    conv = conv_svc.create(db, user, project.id if project else None, body.title)
    audit.record("conversation.created", actor=user, object_type="conversation", object_id=conv.id, project_id=conv.project_id, ip=client_ip(request))
    page = conv_svc.messages_page(db, conv)
    return S.ConversationDetail(**_out(db, conv).model_dump(), messages=page.messages, has_more_before=page.has_more_before, starters=conv_svc.starters_for(db, user, general=conv.project_id is None))


@router.get("", response_model=List[S.ConversationOut])
def list_conversations(q: Optional[str] = Query(default=None, max_length=200), status: str = Query(default="active", pattern="^(active|archived)$"),
                       project_id: Optional[str] = Query(default=None, max_length=64), limit: int = Query(default=50, ge=1, le=100),
                       offset: int = Query(default=0, ge=0), scope: Optional[str] = Query(default=None, pattern="^general$"),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pid = get_membership(db, user, project_id)[0].id if project_id else None
    return conv_svc.list_for(db, user, q=q, status=status, project_id=pid, limit=limit, offset=offset, general_only=scope == "general")


@router.get("/{conversation_id}", response_model=S.ConversationDetail)
def get_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = conv_svc.load(db, user, conversation_id)
    page = conv_svc.messages_page(db, conv)
    return S.ConversationDetail(**_out(db, conv).model_dump(), messages=page.messages, has_more_before=page.has_more_before, starters=conv_svc.starters_for(db, user, general=conv.project_id is None))


@router.get("/{conversation_id}/messages", response_model=S.MessagesPage)
def get_messages(conversation_id: str, before_seq: Optional[int] = Query(default=None, ge=1), limit: int = Query(default=50, ge=1, le=100),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return conv_svc.messages_page(db, conv_svc.load(db, user, conversation_id), before_seq, limit)


@router.post("/{conversation_id}/messages", response_model=S.ChatResponse)
def post_message(conversation_id: str, body: S.MessageIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce("translate", str(user.id), get_settings().rate_limit_translate_per_min)
    conv = conv_svc.load(db, user, conversation_id, allow_archived=False)
    project = db.get(Project, conv.project_id) if conv.project_id else None
    return orchestrator.respond(db, user, conv, project, body.message, body.source_language, body.target_language, body.context_translation_id)


@router.patch("/{conversation_id}", response_model=S.ConversationOut)
def patch(conversation_id: str, body: S.ConversationPatch, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = conv_svc.load(db, user, conversation_id)
    if body.title is not None:
        conv.title = body.title.strip()
    if body.status is not None:
        conv.status = body.status
    db.commit()
    audit.record("conversation.updated", actor=user, object_type="conversation", object_id=conv.id, project_id=conv.project_id,
                 details={"renamed": body.title is not None, "status": conv.status}, ip=client_ip(request))
    return _out(db, conv)


@router.delete("/{conversation_id}", status_code=204)
def delete(conversation_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = conv_svc.load(db, user, conversation_id)
    conv_svc.soft_delete(db, conv)
    audit.record("conversation.deleted", actor=user, object_type="conversation", object_id=conv.id, project_id=conv.project_id, ip=client_ip(request))
