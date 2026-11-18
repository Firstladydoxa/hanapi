"""Approved Translation Memory: exact + fuzzy lookup, always scoped to a project.

Only human-approved translations enter this table (see `promote`). Drafts remain in
`translation_versions` and are never searched here.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.db import Approval, TranslationMemory, TranslationVersion

try:  # rapidfuzz is a hard dependency; difflib fallback keeps unit tests runnable without it
    from rapidfuzz import fuzz

    def _ratio(a: str, b: str) -> int:
        return int(round(fuzz.ratio(a, b)))
except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    def _ratio(a: str, b: str) -> int:
        return int(round(SequenceMatcher(None, a, b).ratio() * 100))

_WS = re.compile(r"\s+")
MAX_FUZZY_CANDIDATES = 3000


def normalise(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def source_hash(text: str) -> str:
    return hashlib.sha256(normalise(text).encode()).hexdigest()


@dataclass
class TMMatch:
    tm_id: uuid.UUID
    source_text: str
    target_text: str
    match_percent: int
    match_type: str
    approved_at: datetime
    project_id: uuid.UUID
    version_id: uuid.UUID
    approval_id: uuid.UUID


def search(
    db: Session,
    project_id: uuid.UUID,
    source_language: str,
    target_language: str,
    query: str,
    *,
    min_match: int = 70,
    limit: int = 10,
) -> List[TMMatch]:
    """Exact (100, same normalised text) and fuzzy matches. EVERY query filters by project_id."""
    q = normalise(query)
    if not q:
        return []
    min_match = max(1, min(100, min_match))
    base = (
        TranslationMemory.project_id == project_id,
        TranslationMemory.source_language == source_language,
        TranslationMemory.target_language == target_language,
        TranslationMemory.active.is_(True),
    )
    out: dict = {}

    def add(row: TranslationMemory, pct: int, kind: str) -> None:
        key = (normalise(row.source_text), normalise(row.target_text))
        cur = out.get(key)
        if cur is None or pct > cur.match_percent:
            out[key] = TMMatch(row.id, row.source_text, row.target_text, pct, kind, row.approved_at, row.project_id,
                               row.version_id, row.approval_id)

    for row in db.execute(select(TranslationMemory).where(*base, TranslationMemory.source_hash == source_hash(q))).scalars():
        add(row, 100, "exact")

    if min_match < 100:
        qlen = len(q)
        slack = int(qlen * (100 - min_match) / 100) + 1  # length difference bounds the best possible ratio
        stmt = (
            select(TranslationMemory)
            .where(*base, func.length(TranslationMemory.source_text).between(max(1, qlen - slack - 5), qlen + slack + 5))
            .order_by(TranslationMemory.approved_at.desc())
            .limit(MAX_FUZZY_CANDIDATES)
        )
        qf = q.casefold()
        for row in db.execute(stmt).scalars():
            if normalise(row.source_text) == q:
                continue
            pct = min(99, _ratio(qf, normalise(row.source_text).casefold()))  # 100 is reserved for exact
            if pct >= min_match:
                add(row, pct, "fuzzy")

    return sorted(out.values(), key=lambda m: (m.match_percent, m.approved_at), reverse=True)[:limit]


def promote(db: Session, approval: Approval, version: TranslationVersion, segment) -> Optional[TranslationMemory]:
    """Create the TM entry for an *approved* approval row (idempotent). Rejections never enter TM."""
    if approval.decision != "approved" or approval.version_id != version.id:
        return None
    existing = db.execute(select(TranslationMemory).where(TranslationMemory.approval_id == approval.id)).scalar_one_or_none()
    if existing:
        return existing
    entry = TranslationMemory(
        project_id=segment.project_id,
        source_language=segment.source_language,
        target_language=segment.target_language,
        source_text=segment.source_text,
        target_text=version.target_text,
        source_hash=source_hash(segment.source_text),
        domain=segment.domain,
        version_id=version.id,
        approval_id=approval.id,
        approved_by=approval.approver_id,
        approved_at=approval.created_at or datetime.utcnow(),
    )
    db.add(entry)
    db.flush()
    return entry
