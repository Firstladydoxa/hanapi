"""Persistent HAN conversations: storage, ordering, greeting, titles, summaries, search, archive and soft deletion."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import ApiError, not_found
from ..models import schemas as S
from ..models.db import ChatConversation, ChatMessage, Project, ProjectMember, User
from ..security.permissions import parse_uuid

STARTERS = [
    "Help me translate a text.",
    "Explain a difficult terminology choice.",
    "Review my translation.",
    "Suggest a more natural expression.",
    "Help me understand a cultural expression.",
    "Explain how to use HAN.",
]
GREETING_NAMED = ("Hello, {name}! {welcome}\n\nI'm here to support your translation work. You can ask me about terminology, translation choices, "
                  "grammar, cultural context or any part of your translation workflow.\n\nWhat are we working on today?")
GREETING_ANON = ("Hello! Welcome to HAN.\n\nI'm your TNI translation assistant. I can help with translation questions, terminology, proofreading "
                 "and language-related challenges.\n\nWhat would you like to work on today?")


def first_name(user: User) -> Optional[str]:
    token = (user.display_name or "").strip().split(" ")[0]
    return token if re.fullmatch(r"[^\W\d_][\w'’-]{1,40}", token) and not re.search(r"\d", token) else None


# ------------------------------------------------------------------ access
def visible_project_ids(db: Session, user: User) -> set:
    rows = db.execute(select(ProjectMember.project_id).join(Project, Project.id == ProjectMember.project_id)
                      .where(ProjectMember.user_id == user.id, Project.status == "active")).scalars()
    return set(rows)


def load(db: Session, user: User, conversation_id: Any, *, allow_archived: bool = True) -> ChatConversation:
    """The caller's own conversation, in a project they still belong to. Anything else is a 404 (existence is never revealed)."""
    try:
        cid = parse_uuid(conversation_id, "conversation")
    except ApiError:
        raise not_found("conversation")
    conv = db.get(ChatConversation, cid)
    if conv is None or conv.user_id != user.id or conv.status == "deleted":
        raise not_found("conversation")
    if conv.project_id is not None and conv.project_id not in visible_project_ids(db, user):
        raise not_found("conversation")
    if conv.status == "archived" and not allow_archived:
        raise ApiError(409, "conversation_archived", "This conversation is archived. Restore it to continue.")
    return conv


# ------------------------------------------------------------------ messages
def _meta(resp: S.ChatResponse, kind: str) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"kind": kind}
    if resp.translation is not None:
        meta["translation"] = resp.translation.model_dump(mode="json")
    if resp.clarification is not None:
        meta["clarification"] = resp.clarification.model_dump(mode="json")
    if resp.actions:
        meta["actions"] = [a.model_dump(mode="json") for a in resp.actions]
    if resp.sources:
        meta["sources"] = [s.model_dump(mode="json") for s in resp.sources]
    return meta


def next_seq(db: Session, conv_id: uuid.UUID) -> int:
    return (db.execute(select(func.max(ChatMessage.seq)).where(ChatMessage.conversation_id == conv_id)).scalar() or 0) + 1


def make_title(text: str) -> str:
    t = re.sub(r"\s+", " ", re.sub(r"^(please |can you |could you )", "", text.strip(), flags=re.I))
    return (t[:57].rstrip() + "…") if len(t) > 60 else (t or "New conversation")


def append_exchange(db: Session, conv: ChatConversation, user_text: str, resp: S.ChatResponse, kind: str, state: Dict[str, Any]) -> ChatMessage:
    """Store the translator's message and HAN's reply in order, then refresh title, summary and ordering timestamps."""
    db.refresh(conv, with_for_update=True)  # serialises concurrent posts to the same conversation so seq stays strictly ordered
    seq = next_seq(db, conv.id)
    db.add(ChatMessage(conversation_id=conv.id, seq=seq, role="user", content=user_text, meta={"kind": "text"}))
    reply = ChatMessage(conversation_id=conv.id, seq=seq + 1, role="assistant", content=resp.reply, meta=_meta(resp, kind))
    db.add(reply)
    conv.state = state
    conv.last_message_at = datetime.now(timezone.utc)
    if not conv.title:
        conv.title = make_title(user_text)
    db.flush()
    refresh_summary(db, conv)
    db.commit()
    resp.message_id, resp.title = str(reply.id), conv.title
    return reply


def message_out(m: ChatMessage) -> S.MessageOut:
    meta = m.meta or {}
    return S.MessageOut(
        id=str(m.id), seq=m.seq, role="assistant" if m.role in ("assistant", "han") else "user", content=m.content, kind=meta.get("kind", "text"),
        created_at=m.created_at, translation=S.TranslateResponse(**meta["translation"]) if meta.get("translation") else None,
        clarification=S.Clarification(**meta["clarification"]) if meta.get("clarification") else None,
        actions=[S.ChatAction(**a) for a in meta.get("actions", [])], sources=[S.SourceRef(**x) for x in meta.get("sources", [])])


def messages_page(db: Session, conv: ChatConversation, before_seq: Optional[int] = None, limit: int = 50) -> S.MessagesPage:
    stmt = select(ChatMessage).where(ChatMessage.conversation_id == conv.id)
    if before_seq:
        stmt = stmt.where(ChatMessage.seq < before_seq)
    rows = list(db.execute(stmt.order_by(ChatMessage.seq.desc()).limit(limit + 1)).scalars())
    more = len(rows) > limit
    return S.MessagesPage(messages=[message_out(m) for m in reversed(rows[:limit])], has_more_before=more)


# ------------------------------------------------------------------ greeting
def create(db: Session, user: User, project_id: Optional[uuid.UUID], title: Optional[str] = None, greet: bool = True) -> ChatConversation:
    earlier = db.execute(select(func.count()).select_from(ChatConversation).where(ChatConversation.user_id == user.id,
                                                                                  ChatConversation.status != "deleted")).scalar() or 0
    conv = ChatConversation(project_id=project_id, user_id=user.id, title=title, state={}, last_message_at=datetime.now(timezone.utc))
    db.add(conv)
    db.flush()
    if greet:  # exactly once, as the first stored message; reloading simply reads it back
        name = first_name(user)
        text = GREETING_NAMED.format(name=name, welcome="Welcome back to HAN." if earlier else "Welcome to HAN.") if name else GREETING_ANON
        db.add(ChatMessage(conversation_id=conv.id, seq=1, role="assistant", content=text, meta={"kind": "greeting"}))
    db.commit()
    return conv


# ------------------------------------------------------------------ context + summary
def refresh_summary(db: Session, conv: ChatConversation) -> None:
    """Rolling, deterministic summary of OLDER messages (never authoritative; the messages themselves always win)."""
    s = get_settings()
    total = db.execute(select(func.max(ChatMessage.seq)).where(ChatMessage.conversation_id == conv.id)).scalar() or 0
    if total <= s.conversation_summary_threshold:
        return
    cutoff = total - s.chat_recent_messages
    if cutoff <= conv.summary_upto:
        return
    rows = db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conv.id, ChatMessage.seq > conv.summary_upto,
                                                ChatMessage.seq <= cutoff).order_by(ChatMessage.seq)).scalars()
    lines = [conv.summary] if conv.summary else []
    for m in rows:
        kind = (m.meta or {}).get("kind")
        if m.role == "user":
            lines.append("- The translator said: " + re.sub(r"\s+", " ", m.content)[:140])
        elif kind == "translation":
            lines.append("- HAN prepared a translation draft.")
    conv.summary = "\n".join(lines)[-1800:]
    conv.summary_upto = cutoff


def history_for_model(db: Session, conv: ChatConversation, current: str) -> tuple[List[Dict[str, str]], Optional[str]]:
    """(recent messages within the character budget, extra earlier messages relevant to `current` or None)."""
    s = get_settings()
    rows = list(db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conv.id).order_by(ChatMessage.seq.desc())
                           .limit(s.chat_recent_messages + 1)).scalars())
    rows = [m for m in reversed(rows) if (m.meta or {}).get("kind") != "greeting"]
    out: List[Dict[str, str]] = []
    used = 0
    for m in reversed(rows):
        text = m.content[:1500]
        if used + len(text) > s.chat_context_chars:
            break
        out.append({"role": "assistant" if m.role in ("assistant", "han") else "user", "content": text})
        used += len(text)
    out.reverse()
    earlier = None
    oldest_seq = rows[0].seq if rows else 0
    if oldest_seq > 2 and re.search(r"\b(earlier|before|previous|previously|you said|you told|again|that term|that word|last time)\b", current, re.I):
        terms = {w for w in re.findall(r"\w{4,}", current.lower())}
        older = db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conv.id, ChatMessage.seq < oldest_seq)
                           .order_by(ChatMessage.seq.desc()).limit(60)).scalars()
        scored = sorted(((len(terms & set(re.findall(r"\w{4,}", m.content.lower()))), m) for m in older), key=lambda x: -x[0])
        picks = [m for sc, m in scored[:2] if sc > 0]
        if picks:
            earlier = "\n".join(f"{'Translator' if m.role == 'user' else 'HAN'}: {m.content[:400]}" for m in sorted(picks, key=lambda m: m.seq))
    return out, earlier


# ------------------------------------------------------------------ list / update / delete
def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def conversation_out(db: Session, conv: ChatConversation, project_names: Dict[uuid.UUID, str]) -> S.ConversationOut:
    count = db.execute(select(func.count()).select_from(ChatMessage).where(ChatMessage.conversation_id == conv.id)).scalar() or 0
    last = db.execute(select(ChatMessage.content).where(ChatMessage.conversation_id == conv.id, ChatMessage.role != "user")
                      .order_by(ChatMessage.seq.desc()).limit(1)).scalar()
    return S.ConversationOut(id=str(conv.id), project_id=str(conv.project_id) if conv.project_id else None,
                             project_name=project_names.get(conv.project_id) if conv.project_id else None, title=conv.title or "New conversation",
                             status=conv.status, created_at=conv.created_at, updated_at=conv.updated_at, last_message_at=conv.last_message_at,
                             message_count=count, preview=(last or "")[:140] or None)


def list_for(db: Session, user: User, *, q: Optional[str] = None, status: str = "active", project_id: Optional[uuid.UUID] = None,
             limit: int = 50, offset: int = 0) -> List[S.ConversationOut]:
    visible = visible_project_ids(db, user)
    stmt = select(ChatConversation).where(ChatConversation.user_id == user.id, ChatConversation.status == status,
                                          or_(ChatConversation.project_id.is_(None), ChatConversation.project_id.in_(visible or {uuid.UUID(int=0)})))
    if project_id:
        stmt = stmt.where(ChatConversation.project_id == project_id)
    if q and q.strip():
        pat = _like(q.strip())
        hit = select(ChatMessage.conversation_id).where(ChatMessage.content.ilike(pat, escape="\\"))
        stmt = stmt.where(or_(ChatConversation.title.ilike(pat, escape="\\"), ChatConversation.id.in_(hit)))
    # conversations that only hold the greeting are not worth listing until the translator writes something
    has_user = select(ChatMessage.conversation_id).where(ChatMessage.role == "user")
    stmt = stmt.where(ChatConversation.id.in_(has_user))
    rows = list(db.execute(stmt.order_by(ChatConversation.last_message_at.desc().nullslast(), ChatConversation.created_at.desc())
                           .limit(limit).offset(offset)).scalars())
    names = dict(db.execute(select(Project.id, Project.name).where(Project.id.in_({c.project_id for c in rows if c.project_id}))).all()) if rows else {}
    return [conversation_out(db, c, names) for c in rows]


def soft_delete(db: Session, conv: ChatConversation) -> None:
    conv.status, conv.deleted_at = "deleted", datetime.now(timezone.utc)
    db.commit()


def purge_deleted(db: Session, older_than_days: Optional[int] = None) -> int:
    """Permanently remove conversations deleted more than the retention period ago (run from the daily maintenance job)."""
    days = get_settings().conversation_retention_days if older_than_days is None else older_than_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    ids = list(db.execute(select(ChatConversation.id).where(ChatConversation.status == "deleted", ChatConversation.deleted_at <= cutoff)).scalars())
    if ids:
        db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(ids)))
        db.execute(delete(ChatConversation).where(ChatConversation.id.in_(ids)))
        db.commit()
    return len(ids)
