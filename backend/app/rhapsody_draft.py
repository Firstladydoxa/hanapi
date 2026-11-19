"""HAN drafting for Rhapsody assignments: paragraph-by-paragraph suggestions from the activated English master.

Order of authority for each paragraph: approved TNI glossary (whole-paragraph match) -> approved translation memory -> HAN's
translation engine, guided by the language glossary and project terminology. Every suggestion is stored as an `ai` version; a
translator has to confirm or edit each one, and an assignment cannot be submitted while an unreviewed draft remains.
"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import glossary, services
from .config import get_settings
from .database import SessionLocal
from .errors import ApiError
from .models.db import (
    Project, RhapsodyAssignment, RhapsodySegment, RhapsodySegmentTranslation, RhapsodyTranslationVersion, User,
)
from .rhapsody_layout import TAG, strip_tags, tags_preserved

log = logging.getLogger("han.rhapsody")
PROJECT_NAME = "Rhapsody of Realities"
ROLE_CONTEXT = {
    "title": "the title of a daily devotional article", "scripture": "the opening Bible verse of a daily devotional article",
    "scripture_ref": "a Bible reference", "body": "a paragraph of a Christian devotional by Pastor Chris Oyakhilome",
    "closing": "the prayer or confession that closes the article", "further_study": "a list of Bible references",
    "plan1": "a list of Bible references", "plan2": "a list of Bible references", "label": "a fixed label of the devotional layout",
    "static": "front or back matter of the devotional", "insert": "a promotional insert of the devotional",
}
_running: set = set()
_lock = threading.Lock()


def rhapsody_project(db: Session) -> Project:
    """The platform project that carries Rhapsody drafts (terminology, translation memory and routing policy)."""
    project = db.execute(select(Project).where(Project.name == PROJECT_NAME)).scalars().first()
    if project is None:
        project = Project(name=PROJECT_NAME, client="TNI", domain="religious devotional", style="faithful, reverent, simple",
                          instructions="Translate Pastor Chris Oyakhilome's Rhapsody of Realities faithfully. Keep Scripture references, names and inline tags unchanged. "
                                       "Never invent doctrinal terms; use the approved TNI glossary.", pilot_opt_in=True)
        db.add(project)
        db.commit()
        db.refresh(project)
    return project


def _protect(text: str) -> Tuple[str, Dict[str, str]]:
    held: Dict[str, str] = {}

    def swap(m: "re.Match[str]") -> str:
        key = f"⟦{len(held) + 1}⟧"
        held[key] = m.group(0)
        return key

    return TAG.sub(swap, text), held


def _restore(text: str, held: Dict[str, str]) -> Optional[str]:
    if any(text.count(k) != 1 for k in held):
        return None
    for k, v in held.items():
        text = text.replace(k, v)
    return text


def _terms(db: Session, project: Project, target: str, text: str):
    entries = glossary.find_in_text(db, target, strip_tags(text))
    own = [SimpleNamespace(source_term=e.source_text, target_term=e.target_text) for e in entries]
    _, project_terms = services.retrieve_context(db, project, "en", target, text)
    return own + [t for t in project_terms if t.source_term.lower() not in {o.source_term.lower() for o in own}], entries


def draft_text(db: Session, user: User, project: Project, target: str, text: str, role: str) -> Tuple[str, Dict[str, Any]]:
    """One suggestion and how it was produced. Raises ApiError when the language pair cannot be drafted."""
    plain = strip_tags(text)
    exact = glossary.get_exact(db, target, plain) if plain else None
    if exact is not None and not TAG.search(text):
        return exact.target_text, {"source": "glossary", "warnings": []}
    matches, _ = services.retrieve_context(db, project, "en", target, text)
    best = next((m for m in matches if m.match_percent >= 100 and tags_preserved(text, m.target_text)), None)
    if best is not None:
        return best.target_text, {"source": "tm", "warnings": []}
    terms, entries = _terms(db, project, target, text)
    protected, held = _protect(text)
    warnings: List[str] = []
    translated = services.run_gateway(db, user, project, "en", target, protected, context=f"This is {ROLE_CONTEXT.get(role, 'devotional text')}."
                                      + (" Keep the placeholders such as ⟦1⟧ exactly where they belong." if held else ""),
                                      domain=project.domain, terms=terms, segment_id=uuid.uuid4())
    if held:
        restored = _restore(translated, held)
        if restored is None:
            translated = re.sub(r"⟦\d+⟧", "", translated)
            warnings.append("Layout tags could not be kept in this draft. Re-insert " + " ".join(held.values()) + " where they belong.")
        else:
            translated = restored
    if role in {"scripture", "scripture_ref"}:
        warnings.append("Scripture: replace this with the approved Bible text for the language rather than relying on the draft.")
    meta: Dict[str, Any] = {"source": "model", "warnings": warnings}
    if entries:
        meta["glossary"] = [{"source": e.source_text, "target": e.target_text} for e in entries[:8]]
    return translated.strip(), meta


def prefill_locked(db: Session, assignment: RhapsodyAssignment, user: User) -> int:
    """Phone numbers, web addresses and codes are carried over unchanged so the translator only sees real text."""
    rows = db.execute(select(RhapsodySegmentTranslation, RhapsodySegment).join(RhapsodySegment, RhapsodySegment.id == RhapsodySegmentTranslation.segment_id)
                      .where(RhapsodySegmentTranslation.assignment_id == assignment.id, RhapsodySegmentTranslation.current_version_id.is_(None))).all()
    n = 0
    for tr, seg in rows:
        if (seg.metadata_json or {}).get("locked"):
            v = RhapsodyTranslationVersion(segment_translation_id=tr.id, version_number=1, target_text=seg.source_text, origin="human",
                                           created_by=user.id, meta={"source": "locked", "warnings": []})
            db.add(v)
            db.flush()
            tr.current_version_id, tr.status = v.id, "draft"
            n += 1
    db.commit()
    return n


def draft_one(db: Session, user: User, assignment: RhapsodyAssignment, tr: RhapsodySegmentTranslation, seg: RhapsodySegment,
              project: Project) -> RhapsodyTranslationVersion:
    text, meta = draft_text(db, user, project, assignment.target_language, seg.source_text, (seg.metadata_json or {}).get("role", "body"))
    current = db.get(RhapsodyTranslationVersion, tr.current_version_id) if tr.current_version_id else None
    v = RhapsodyTranslationVersion(segment_translation_id=tr.id, version_number=(current.version_number + 1) if current else 1, target_text=text,
                                   origin="ai", created_by=user.id, parent_version_id=current.id if current else None, meta=meta)
    db.add(v)
    db.flush()
    tr.current_version_id, tr.status = v.id, "draft"
    db.commit()
    return v


def _run(assignment_id: uuid.UUID, user_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        a = db.get(RhapsodyAssignment, assignment_id)
        user = db.get(User, user_id)
        if a is None or user is None:
            return
        try:
            project = rhapsody_project(db)
            tier = services.ensure_direction_allowed(db, project, "en", a.target_language)
            note, _ = services.readiness_warnings(tier)
            a.draft_note = note
            pending = db.execute(select(RhapsodySegmentTranslation, RhapsodySegment).join(RhapsodySegment, RhapsodySegment.id == RhapsodySegmentTranslation.segment_id)
                                 .where(RhapsodySegmentTranslation.assignment_id == a.id, RhapsodySegmentTranslation.current_version_id.is_(None))
                                 .order_by(RhapsodySegment.sequence)).all()
            total = db.execute(select(RhapsodySegmentTranslation.id).where(RhapsodySegmentTranslation.assignment_id == a.id)).all()
            a.draft_total, a.draft_done, a.draft_status = len(total), len(total) - len(pending), "running"
            db.commit()
            for tr, seg in pending:
                try:
                    draft_one(db, user, a, tr, seg, project)
                except ApiError as e:
                    if e.code in {"direction_unsupported", "translation_unavailable", "quota_exceeded"}:
                        raise
                    db.rollback()
                    log.warning("rhapsody draft skipped for segment %s: %s", seg.id, e.code)
                except Exception:
                    db.rollback()
                    log.exception("rhapsody draft failed for segment %s", seg.id)
                db.execute(update(RhapsodyAssignment).where(RhapsodyAssignment.id == a.id).values(draft_done=RhapsodyAssignment.draft_done + 1))
                db.commit()
            a = db.get(RhapsodyAssignment, assignment_id)
            a.draft_status = "done"
            if a.status == "assigned":
                a.status = "in_progress"
            db.commit()
        except ApiError as e:
            db.rollback()
            a = db.get(RhapsodyAssignment, assignment_id)
            a.draft_status, a.draft_note = "failed", e.message[:500]
            db.commit()
        except Exception:
            log.exception("rhapsody drafting crashed")
            db.rollback()
            a = db.get(RhapsodyAssignment, assignment_id)
            a.draft_status, a.draft_note = "failed", "HAN could not finish the draft. Please try again."
            db.commit()
        finally:
            with _lock:
                _running.discard(assignment_id)


def start_drafting(db: Session, assignment: RhapsodyAssignment, user: User) -> bool:
    """Begin (or resume) drafting every paragraph that has no text yet. False when a run is already in progress."""
    with _lock:
        if assignment.id in _running:
            return False
        _running.add(assignment.id)
    prefill_locked(db, assignment, user)
    assignment.draft_status = "running"
    db.commit()
    if get_settings().jobs_eager:
        _run(assignment.id, user.id)
    else:
        threading.Thread(target=_run, args=(assignment.id, user.id), name=f"han-rhapsody-{assignment.id}", daemon=True).start()
    return True
