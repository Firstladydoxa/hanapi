"""Terminology service: approved-only for translators, global glossary only when scope='global'."""
from __future__ import annotations

import re
import uuid
from typing import List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models.db import TerminologyApproval, TerminologyEntry


def _visible(project_id: uuid.UUID):
    return or_(
        TerminologyEntry.project_id == project_id,
        and_(TerminologyEntry.scope == "global", TerminologyEntry.project_id.is_(None)),
    )


def search(
    db: Session,
    project_id: uuid.UUID,
    source_language: str,
    target_language: str,
    q: str = "",
    domain: Optional[str] = None,
    limit: int = 50,
) -> List[TerminologyEntry]:
    """Approved entries visible to the project (its own + global scope)."""
    stmt = select(TerminologyEntry).where(
        _visible(project_id),
        TerminologyEntry.status == "approved",
        TerminologyEntry.source_language == source_language,
        TerminologyEntry.target_language == target_language,
    )
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(or_(TerminologyEntry.source_term.ilike(like), TerminologyEntry.target_term.ilike(like)))
    if domain:
        stmt = stmt.where(TerminologyEntry.domain == domain)
    return list(db.execute(stmt.order_by(TerminologyEntry.source_term).limit(limit)).scalars())


def _contains_term(text: str, term: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)"
    return re.search(pattern, text.casefold()) is not None


def find_in_text(db: Session, project_id: uuid.UUID, source_language: str, target_language: str, text: str) -> List[TerminologyEntry]:
    """Approved terms whose source term occurs in `text` (longest first)."""
    entries = search(db, project_id, source_language, target_language, limit=2000)
    hits = [e for e in entries if _contains_term(text, e.source_term)]
    return sorted(hits, key=lambda e: -len(e.source_term))


def contains_term(text: str, term: str) -> bool:
    return _contains_term(text, term)


def record_status_change(db: Session, entry: TerminologyEntry, actor_id: uuid.UUID, from_status: Optional[str], to_status: str,
                         comment: Optional[str] = None) -> None:
    db.add(TerminologyApproval(entry_id=entry.id, actor_id=actor_id, from_status=from_status, to_status=to_status, comment=comment))
