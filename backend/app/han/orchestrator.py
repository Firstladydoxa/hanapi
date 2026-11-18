"""HAN orchestrator: turns a chat message into permitted tool calls and a translator-facing reply.

Never calls an approval capability (there is none in `han.tools.TOOLS`), never mentions engines/providers,
and asks a single focused clarification question when essential information is missing.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import ApiError
from ..models import schemas as S
from ..models.db import ChatConversation, ChatMessage, Language, User
from ..security.permissions import get_membership, parse_uuid
from . import responses as R
from . import tools
from .intents import LanguageIndex, Parsed, parse



def _language_index(db: Session) -> LanguageIndex:
    rows = db.execute(select(Language.code, Language.display_name).where(Language.active.is_(True))).all()
    return LanguageIndex({c: n for c, n in rows})


def _conversation(db: Session, user: User, project_id: uuid.UUID, conversation_id: Optional[str]) -> ChatConversation:
    if conversation_id:
        conv = db.get(ChatConversation, parse_uuid(conversation_id, "conversation"))
        if conv is None or conv.user_id != user.id or conv.project_id != project_id:
            raise ApiError(404, "not_found", "The requested conversation was not found.")
        return conv
    conv = ChatConversation(project_id=project_id, user_id=user.id, state={})
    db.add(conv)
    db.commit()  # persisted up front so a later rollback (e.g. a failed translation) cannot discard it
    return conv


def _finish(db: Session, conv: ChatConversation, user_message: str, response: S.ChatResponse, state: Dict[str, Any]) -> S.ChatResponse:
    conv.state = state
    db.add(ChatMessage(conversation_id=conv.id, role="user", content=user_message))
    db.add(ChatMessage(conversation_id=conv.id, role="han", content=response.reply))
    db.commit()
    return response


def handle(db: Session, user: User, req: S.ChatRequest) -> S.ChatResponse:
    project, _ = get_membership(db, user, req.project_id)
    conv = _conversation(db, user, project.id, req.conversation_id)
    state: Dict[str, Any] = dict(conv.state or {})
    idx = _language_index(db)
    parsed: Parsed = parse(req.message, idx)
    cid = str(conv.id)

    def reply(text: str, **kw: Any) -> S.ChatResponse:
        return S.ChatResponse(conversation_id=cid, reply=text, **kw)

    if parsed.kind == "engine":
        return _finish(db, conv, req.message, reply(R.ENGINE_DEFLECTION), state)
    if parsed.kind == "approve":
        return _finish(db, conv, req.message, reply(R.APPROVAL_EXPLANATION), state)
    if parsed.kind == "greeting":
        return _finish(db, conv, req.message, reply(R.INTRO), state)

    pending: Dict[str, Any] = dict(state.get("pending") or {})
    text, source, target = pending.get("text"), pending.get("source"), pending.get("target")

    if parsed.kind == "language_only" and pending:
        # a bare language answers whichever language is missing
        if not target:
            target = parsed.target
        elif not source:
            source = parsed.target
    elif parsed.kind == "text_only" and pending and not text:
        text = parsed.text
    elif parsed.kind == "translate":
        text = parsed.text or text
        source = parsed.source or source
        target = parsed.target or target
        if parsed.unknown_language:
            return _finish(db, conv, req.message, reply(R.UNKNOWN_LANGUAGE), {"pending": {"text": text, "source": source, "target": target}})
    elif parsed.kind in ("language_only", "text_only"):
        return _finish(db, conv, req.message, reply(R.HELP_FALLBACK), state)

    source = source or req.source_language
    target = target or req.target_language

    # one focused question at a time
    if not text:
        return _ask(db, conv, req.message, cid, R.ASK_TEXT, "text", {"text": text, "source": source, "target": target})
    if not target:
        return _ask(db, conv, req.message, cid, R.ASK_TARGET, "target_language", {"text": text, "source": source, "target": target})
    if not source:
        return _ask(db, conv, req.message, cid, R.ASK_SOURCE, "source_language", {"text": text, "source": source, "target": target})
    if len(text) > get_settings().max_text_chars:
        return _finish(db, conv, req.message, reply("That's a long text. Please use the Translation Workspace for longer documents."), {})

    try:
        result = tools.translate(db, user, project.id, source, target, text)
    except ApiError as e:
        message = {"direction_unsupported": R.UNSUPPORTED, "quota_exceeded": R.QUOTA}.get(e.code, R.UNAVAILABLE)
        if e.status == 404:
            raise
        db.rollback()
        conv = db.get(ChatConversation, conv.id)
        return _finish(db, conv, req.message, reply(message), {"pending": {"text": text, "source": source, "target": target}} if e.code == "translation_unavailable" else {})

    body = R.SUCCESS.format(translation=result.translated_text)
    if any(w.type == "terminology" for w in result.warnings):
        body += "\n\n" + R.UNCERTAIN_TERM
    response = reply(body, translation=result, actions=[S.ChatAction(type="open_in_workspace", translation_id=result.translation_id)])
    return _finish(db, conv, req.message, response, {})


def _ask(db: Session, conv: ChatConversation, message: str, cid: str, question: str, field: str, pending: Dict[str, Any]) -> S.ChatResponse:
    resp = S.ChatResponse(conversation_id=cid, reply=question, clarification=S.Clarification(question=question, field=field))
    return _finish(db, conv, message, resp, {"pending": pending})
