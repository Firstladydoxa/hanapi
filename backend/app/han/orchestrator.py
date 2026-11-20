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
from ..models.db import ChatConversation, Language, Project, User
from ..security.permissions import get_membership, parse_uuid
from . import conversations, intelligence
from . import responses as R
from . import tools
from .intents import LanguageIndex, Parsed, parse



def _language_index(db: Session) -> LanguageIndex:
    rows = db.execute(select(Language.code, Language.display_name).where(Language.active.is_(True))).all()
    return LanguageIndex({c: n for c, n in rows})


def _finish(db: Session, conv: ChatConversation, user_message: str, response: S.ChatResponse, state: Dict[str, Any], kind: str = "answer") -> S.ChatResponse:
    conversations.append_exchange(db, conv, user_message, response, kind, state)
    return response


def handle(db: Session, user: User, req: S.ChatRequest) -> S.ChatResponse:
    """Legacy entry point (`POST /v1/chat`): a project-scoped message, creating a conversation (without a greeting) when none is given."""
    project, _ = get_membership(db, user, req.project_id)
    if req.conversation_id:
        conv = conversations.load(db, user, req.conversation_id, allow_archived=False)
        if conv.project_id != project.id:
            raise ApiError(404, "not_found", "The requested conversation was not found.")
    else:
        conv = conversations.create(db, user, project.id, greet=False)
    return respond(db, user, conv, project, req.message, req.source_language, req.target_language, req.context_translation_id)


def respond(db: Session, user: User, conv: ChatConversation, project: Optional[Project], message: str,
            source_language: Optional[str] = None, target_language: Optional[str] = None,
            context_translation_id: Optional[str] = None) -> S.ChatResponse:
    state: Dict[str, Any] = dict(conv.state or {})
    idx = _language_index(db)
    parsed: Parsed = parse(message, idx)
    cid = str(conv.id)

    def reply(text: str, **kw: Any) -> S.ChatResponse:
        return S.ChatResponse(conversation_id=cid, reply=text, **kw)

    def talk(intent: str) -> S.ChatResponse:
        a = intelligence.answer(db, user, conv, project, message, intent, idx, state, (parsed.source, parsed.target), context_translation_id)
        return _finish(db, conv, message, reply(a.reply, sources=a.sources), state, a.kind)

    from . import guide, rhapsody_chat

    handled = guide.handle(db, user, message) or rhapsody_chat.handle(db, user, message, idx)
    if handled is not None:
        return _finish(db, conv, message, reply(handled.text, actions=handled.actions), state, "answer")

    if intelligence.classify(message) == "glossary":  # "give me the translation of X in German, per the glossary" is a lookup, not a draft request
        return talk("glossary")

    if parsed.kind == "engine":
        return _finish(db, conv, message, reply(R.ENGINE_DEFLECTION), state)
    if parsed.kind == "approve":
        return _finish(db, conv, message, reply(R.APPROVAL_EXPLANATION), state)
    if parsed.kind == "greeting":
        return _finish(db, conv, message, reply(intelligence.greeting_reply(db, conv)), state)

    pending: Dict[str, Any] = dict(state.get("pending") or {})
    text, source, target = pending.get("text"), pending.get("source"), pending.get("target")

    if parsed.kind == "language_only" and pending:
        if not target:
            target = parsed.target
        elif not source:
            source = parsed.target
    elif parsed.kind == "text_only" and pending and not text:
        text = parsed.text
    elif parsed.kind == "translate":
        # a question about translation ("how do I translate X?") is conversation, not a request for a draft
        intent = intelligence.classify(message)
        if not parsed.text and not pending and intent in ("language_support", "platform_help", "terminology", "tni_info", "grammar", "cultural", "review", "rewrite", "explain", "doctrine"):
            return talk(intent)
        text = parsed.text or text
        source = parsed.source or source
        target = parsed.target or target
        if parsed.unknown_language:
            return _finish(db, conv, message, reply(R.UNKNOWN_LANGUAGE), {"pending": {"text": text, "source": source, "target": target}})
    elif parsed.kind in ("language_only", "text_only"):
        return talk(intelligence.classify(message))
    else:
        return talk(intelligence.classify(message))

    if project is None:
        return _finish(db, conv, message, reply("Please open a project first so I know where to save the draft. Pick one from the Projects page, then ask again."), state)

    source = source or source_language
    target = target or target_language
    if not target and user.role == "translator" and user.expertise_language:
        # no language named: draft in the translator's own pair (English -> expertise, or expertise -> English)
        target = "en" if source == user.expertise_language else user.expertise_language

    if not text:
        return _ask(db, conv, message, cid, R.ASK_TEXT, "text", {"text": text, "source": source, "target": target})
    if not target:
        return _ask(db, conv, message, cid, R.ASK_TARGET, "target_language", {"text": text, "source": source, "target": target})
    if not source and text:
        from . import detect

        source = detect.detect_source(text, target)
    if not source:
        return _ask(db, conv, message, cid, R.ASK_SOURCE, "source_language", {"text": text, "source": source, "target": target})
    if len(text) > get_settings().max_text_chars:
        return _finish(db, conv, message, reply("That's a long text. Please use the Translation Workspace for longer documents."), {})

    try:
        result = tools.translate(db, user, project.id, source, target, text)
    except ApiError as e:
        message_text = {"direction_unsupported": R.UNSUPPORTED, "quota_exceeded": R.QUOTA}.get(e.code, R.UNAVAILABLE)
        if e.status == 404:
            raise
        db.rollback()
        conv = db.get(ChatConversation, conv.id)
        return _finish(db, conv, message, reply(message_text), {"pending": {"text": text, "source": source, "target": target}} if e.code == "translation_unavailable" else {})

    body = R.SUCCESS.format(translation=result.translated_text)
    if any(w.type == "terminology" for w in result.warnings):
        body += "\n\n" + R.UNCERTAIN_TERM
    response = reply(body, translation=result, actions=[S.ChatAction(type="open_in_workspace", translation_id=result.translation_id)])
    return _finish(db, conv, message, response, {}, "translation")


def _ask(db: Session, conv: ChatConversation, message: str, cid: str, question: str, field: str, pending: Dict[str, Any]) -> S.ChatResponse:
    resp = S.ChatResponse(conversation_id=cid, reply=question, clarification=S.Clarification(question=question, field=field))
    return _finish(db, conv, message, resp, {"pending": pending}, "clarification")
