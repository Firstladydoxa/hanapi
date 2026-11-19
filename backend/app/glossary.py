"""Per-language TNI glossary of frequently translated words, expressions and sentences (English source).

Entries are entered by the language's team leader (or an administrator) and are authoritative: HAN quotes them as-is and never improvises.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from typing import List, Optional, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models.db import GlossaryEntry, GlossaryLead, User
from .security.permissions import ADMIN_ROLES

KINDS = ("word", "expression", "sentence")
_EDGE = " \t\r\n\"'“”‘’«».,;:!?¡¿()[]"


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"\s+", " ", t).strip(_EDGE)


def key_of(text: str) -> str:
    return hashlib.sha256(normalise(text).encode()).hexdigest()


def guess_kind(text: str) -> str:
    n = len(normalise(text).split())
    return "word" if n <= 1 else "expression" if n <= 8 else "sentence"


def managed_languages(db: Session, user: User) -> Optional[List[str]]:
    """Language codes the user may edit; None means all (administrators)."""
    if user.role in ADMIN_ROLES:
        return None
    if user.role != "team_leader":
        return []
    return list(db.execute(select(GlossaryLead.language).where(GlossaryLead.user_id == user.id)).scalars())


def can_manage(db: Session, user: User, language: str) -> bool:
    langs = managed_languages(db, user)
    return langs is None or language in langs


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search(db: Session, language: str, q: str = "", kind: Optional[str] = None, limit: int = 50, offset: int = 0):
    stmt = select(GlossaryEntry).where(GlossaryEntry.language == language)
    if q.strip():
        stmt = stmt.where(or_(GlossaryEntry.source_text.ilike(_like(q.strip())), GlossaryEntry.target_text.ilike(_like(q.strip())),
                              GlossaryEntry.notes.ilike(_like(q.strip()))))
    if kind:
        stmt = stmt.where(GlossaryEntry.kind == kind)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = list(db.execute(stmt.order_by(func.lower(GlossaryEntry.source_text)).limit(limit).offset(offset)).scalars())
    return total, rows


def get_exact(db: Session, language: str, phrase: str) -> Optional[GlossaryEntry]:
    return db.execute(select(GlossaryEntry).where(GlossaryEntry.language == language, GlossaryEntry.source_key == key_of(phrase))).scalar_one_or_none()


def find_in_text(db: Session, language: str, text: str) -> List[GlossaryEntry]:
    """Entries whose English source occurs in `text`, longest first (so a full expression beats the words inside it)."""
    low = normalise(text)
    out = [e for e in db.execute(select(GlossaryEntry).where(GlossaryEntry.language == language)).scalars()
           if re.search(r"(?<!\w)" + re.escape(normalise(e.source_text)) + r"(?!\w)", low)]
    return sorted(out, key=lambda e: -len(e.source_text))


def similar(db: Session, language: str, phrase: str, limit: int = 5) -> List[GlossaryEntry]:
    n = normalise(phrase)
    if not n:
        return []
    return list(db.execute(select(GlossaryEntry).where(GlossaryEntry.language == language, GlossaryEntry.source_text.ilike(_like(n)))
                           .order_by(func.length(GlossaryEntry.source_text)).limit(limit)).scalars())


def upsert(db: Session, actor: User, language: str, source: str, target: str, kind: Optional[str] = None, notes: Optional[str] = None) -> tuple[GlossaryEntry, bool]:
    """Create the entry or update the existing one with the same English text. Returns (entry, created)."""
    e = get_exact(db, language, source)
    created = e is None
    if created:
        e = GlossaryEntry(language=language, source_text=source.strip(), source_key=key_of(source), created_by=actor.id)
        db.add(e)
    e.target_text = target.strip()
    e.kind = kind if kind in KINDS else (e.kind if not created and e.kind else guess_kind(source))
    e.notes = (notes or "").strip() or None
    e.updated_by = actor.id
    return e, created


def counts(db: Session) -> dict:
    return {lang: n for lang, n in db.execute(select(GlossaryEntry.language, func.count()).group_by(GlossaryEntry.language)).all()}


def leaders(db: Session) -> dict:
    out: dict[str, List[str]] = {}
    for lang, name in db.execute(select(GlossaryLead.language, User.display_name).join(User, User.id == GlossaryLead.user_id).order_by(User.display_name)).all():
        out.setdefault(lang, []).append(name)
    return out


def set_leads(db: Session, user_id: uuid.UUID, languages: Sequence[str]) -> None:
    db.query(GlossaryLead).filter(GlossaryLead.user_id == user_id).delete()
    for lang in dict.fromkeys(languages):
        db.add(GlossaryLead(user_id=user_id, language=lang))
