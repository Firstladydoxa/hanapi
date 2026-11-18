"""Translation workflow services shared by the REST API, jobs and the HAN orchestrator tools.

Rules enforced here (spec §10.1): versions are only ever inserted; approval is attached to a specific
version; editing creates a new unapproved version; only a `HumanActor` can record an approval.
"""
from __future__ import annotations

import difflib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from .database import SessionLocal
from .errors import UNAVAILABLE_MESSAGE, UNSUPPORTED_MESSAGE, ApiError, not_found
from .logging_config import fingerprint
from .memory import translation_memory as tm
from .models import schemas as S
from .models.db import (
    Approval,
    LanguageDirection,
    Project,
    ProjectDirection,
    ProjectMember,
    RoutingEvent,
    Segment,
    TranslationVersion,
    User,
)
from .models.gateway import ModelGateway, QuotaExceeded, TranslationUnavailable
from .models.router import DirectionUnsupported, direction_tier
from .qa.runner import run_all
from .security import serializers as ser
from .security.permissions import HumanActor, assert_human, effective_can_approve
from .terminology import terminology as term_service

SUGGESTED_MESSAGE = "Here is my suggested translation. Please review it and make any corrections before approving it."
APPROVED_MESSAGE = "Your approved translation has been saved to the project's Translation Memory."
REJECTED_MESSAGE = "Your decision has been recorded. This version will not be added to the Translation Memory."

TIER_NOTES = {
    "assisted": "This language pair is still being evaluated. Please give this draft an especially careful review.",
    "experimental": "This language pair is in a controlled pilot. Treat this draft as an early suggestion and review it thoroughly.",
}


# ---------------------------------------------------------------------------------- readiness
def ensure_direction_allowed(db: Session, project: Project, source: str, target: str) -> str:
    """Returns the readiness tier or raises 422 direction_unsupported with an escalation message."""
    if source == target:
        raise ApiError(422, "same_language", "Please choose two different languages.")
    restricted = db.execute(select(func.count()).select_from(ProjectDirection).where(ProjectDirection.project_id == project.id)).scalar_one()
    if restricted and db.get(ProjectDirection, (project.id, source, target)) is None:
        raise ApiError(422, "direction_unsupported", UNSUPPORTED_MESSAGE)
    tier = direction_tier(db, source, target)
    if tier == "unsupported" or (tier == "experimental" and not project.pilot_opt_in):
        raise ApiError(422, "direction_unsupported", UNSUPPORTED_MESSAGE)
    return tier


def readiness_warnings(tier: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    note = TIER_NOTES.get(tier)
    if not note:
        return None, []
    return note, [{"type": "readiness", "severity": "warning" if tier == "experimental" else "info", "message": note, "span": None}]


# ---------------------------------------------------------------------------------- retrieval
def retrieve_context(db: Session, project: Project, source: str, target: str, text: str):
    matches = tm.search(db, project.id, source, target, text, min_match=get_settings().tm_min_match, limit=5)
    terms = term_service.find_in_text(db, project.id, source, target, text)
    return matches, terms


def tm_out(matches: Sequence[tm.TMMatch]) -> List[S.TMMatchOut]:
    return [S.TMMatchOut(source_text=m.source_text, target_text=m.target_text, match_percent=m.match_percent, tm_id=str(m.tm_id)) for m in matches]


def terms_out(terms) -> List[S.TermOut]:
    return [S.TermOut(source_term=t.source_term, target_term=t.target_term, usage_note=t.usage_note,
                      forbidden=[str(x) for x in (t.forbidden_alternatives or [])]) for t in terms]


# ---------------------------------------------------------------------------------- translate
def _attach_routing(segment_id: uuid.UUID, version_id: uuid.UUID) -> None:
    with SessionLocal() as s:
        s.execute(update(RoutingEvent).where(RoutingEvent.segment_id == segment_id).values(version_id=version_id))
        s.commit()


def run_gateway(db: Session, user: User, project: Project, source: str, target: str, text: str, *, context: Optional[str],
                domain: Optional[str], terms, segment_id: uuid.UUID) -> str:
    """Call the model gateway and map internal failures to generic, engine-agnostic API errors."""
    glossary = [{"source": t.source_term, "target": t.target_term} for t in terms]
    try:
        result = ModelGateway().translate(db, project, source, target, text, user_id=user.id, context=context, domain=domain,
                                          glossary=glossary, segment_id=segment_id)
    except DirectionUnsupported:
        raise ApiError(422, "direction_unsupported", UNSUPPORTED_MESSAGE)
    except QuotaExceeded:
        raise ApiError(429, "quota_exceeded", "This project has reached its translation allowance. Please contact your project manager.")
    except TranslationUnavailable:
        raise ApiError(503, "translation_unavailable", UNAVAILABLE_MESSAGE)
    return result.text


def create_draft(db: Session, user: User, project: Project, source: str, target: str, text: str, *, context: Optional[str] = None,
                 domain: Optional[str] = None, job_id: Optional[uuid.UUID] = None, sequence: int = 0,
                 workflow: str = "translate") -> Tuple[Segment, TranslationVersion, List[Dict[str, Any]], List[tm.TMMatch], list, Optional[str]]:
    tier = ensure_direction_allowed(db, project, source, target)
    matches, terms = retrieve_context(db, project, source, target, text)
    segment_id = uuid.uuid4()
    translated = run_gateway(db, user, project, source, target, text, context=context, domain=domain or project.domain, terms=terms,
                             segment_id=segment_id)
    seg = Segment(id=segment_id, project_id=project.id, job_id=job_id, sequence=sequence, source_language=source, target_language=target,
                  source_text=text, context=context, domain=domain or project.domain, status="draft", created_by=user.id)
    db.add(seg)
    db.flush()
    ver = TranslationVersion(segment_id=seg.id, version_number=1, target_text=translated, origin="ai", created_by=user.id,
                             workflow=workflow)
    db.add(ver)
    db.commit()
    _attach_routing(seg.id, ver.id)
    note, tier_warnings = readiness_warnings(tier)
    warnings = tier_warnings + run_all(db, project.id, text, translated, source, target, terms=terms)
    audit.record("translation.draft_created", actor=user, object_type="translation", object_id=seg.id, project_id=project.id,
                 details={"source": source, "target": target, "chars": len(text), "workflow": workflow})
    return seg, ver, warnings, matches, terms, note


def generate_into_segment(db: Session, user: User, project: Project, seg: Segment) -> TranslationVersion:
    """Fill a pre-created (job) segment with its first AI draft version."""
    ensure_direction_allowed(db, project, seg.source_language, seg.target_language)
    _, terms = retrieve_context(db, project, seg.source_language, seg.target_language, seg.source_text)
    translated = run_gateway(db, user, project, seg.source_language, seg.target_language, seg.source_text, context=seg.context,
                             domain=seg.domain, terms=terms, segment_id=seg.id)
    ver = TranslationVersion(segment_id=seg.id, version_number=1, target_text=translated, origin="ai", created_by=user.id, workflow="job")
    db.add(ver)
    seg.status = "draft"
    db.commit()
    _attach_routing(seg.id, ver.id)
    return ver


def translate_response(seg: Segment, ver: TranslationVersion, warnings, matches, terms, note) -> S.TranslateResponse:
    return S.TranslateResponse(
        translation_id=str(seg.id), version_id=str(ver.id), source_language=seg.source_language, target_language=seg.target_language,
        source_text=seg.source_text, translated_text=ver.target_text, review_note=note, warnings=ser.warnings_out(warnings),
        tm_matches=tm_out(matches), terminology=terms_out(terms), message=SUGGESTED_MESSAGE,
    )


# ---------------------------------------------------------------------------------- versions
def list_versions(db: Session, segment_id: uuid.UUID) -> List[TranslationVersion]:
    return list(db.execute(select(TranslationVersion).where(TranslationVersion.segment_id == segment_id)
                           .order_by(TranslationVersion.version_number)).scalars())


def latest_version(db: Session, segment_id: uuid.UUID) -> Optional[TranslationVersion]:
    return db.execute(select(TranslationVersion).where(TranslationVersion.segment_id == segment_id)
                      .order_by(TranslationVersion.version_number.desc()).limit(1)).scalar_one_or_none()


def save_version(db: Session, user: User, segment: Segment, target_text: str, parent_version_id: object,
                 change_note: Optional[str] = None, origin: str = "human", workflow: str = "edit") -> TranslationVersion:
    """Always inserts a NEW row. The segment row must already be locked by the caller (FOR UPDATE)."""
    try:
        parent_id = parent_version_id if isinstance(parent_version_id, uuid.UUID) else uuid.UUID(str(parent_version_id))
    except ValueError:
        raise not_found("translation version")
    parent = db.execute(select(TranslationVersion).where(TranslationVersion.id == parent_id,
                                                         TranslationVersion.segment_id == segment.id)).scalar_one_or_none()
    if parent is None:
        raise not_found("translation version")
    number = (db.execute(select(func.max(TranslationVersion.version_number)).where(TranslationVersion.segment_id == segment.id)).scalar_one() or 0) + 1
    ver = TranslationVersion(segment_id=segment.id, version_number=number, target_text=target_text, origin=origin, created_by=user.id,
                             parent_version_id=parent.id, change_note=change_note, workflow=workflow)
    db.add(ver)
    segment.status = "in_review"  # any new version (including an edit of an approved one) is unapproved again
    db.commit()
    audit.record("translation.version_saved", actor=user, object_type="translation", object_id=segment.id, project_id=segment.project_id,
                 details={"version_number": number, "text": fingerprint(target_text)})
    return ver


# ---------------------------------------------------------------------------------- approval
def approve_version(db: Session, actor: HumanActor, segment: Segment, member: ProjectMember, version_id: object, decision: str,
                    comment: Optional[str]) -> Tuple[TranslationVersion, Approval]:
    """Human-only. Records the decision on one specific version; promotes to approved TM on approval."""
    assert_human(actor)
    user = actor.user
    if not effective_can_approve(member):
        audit.record("approval.denied", actor=user, outcome="denied", object_type="translation", object_id=segment.id, project_id=segment.project_id)
        raise ApiError(403, "approval_not_permitted", "You do not have permission to approve translations in this project.")
    ver = db.execute(select(TranslationVersion).where(TranslationVersion.id == version_id, TranslationVersion.segment_id == segment.id)).scalar_one_or_none()
    if ver is None:
        raise not_found("translation version")
    newest = latest_version(db, segment.id)
    if newest is None or newest.id != ver.id:
        raise ApiError(409, "version_superseded", "A newer version exists. Please review the latest version.")
    if db.execute(select(Approval).where(Approval.version_id == ver.id)).scalar_one_or_none() is not None:
        raise ApiError(409, "already_decided", "A decision has already been recorded for this version.")
    approval = Approval(version_id=ver.id, approver_id=user.id, decision=decision, comment=comment,
                        created_at=datetime.now(timezone.utc))
    db.add(approval)
    db.flush()
    segment.status = "approved" if decision == "approved" else "rejected"
    if decision == "approved":
        from .han.tools import save_approved_translation  # the only promotion path; verifies the approval row

        save_approved_translation(db, approval.id)
    db.commit()
    audit.record(f"approval.{decision}", actor=user, object_type="version", object_id=ver.id, project_id=segment.project_id,
                 details={"segment_id": str(segment.id)})
    return ver, approval


# ---------------------------------------------------------------------------------- compare
def compare_versions(a: TranslationVersion, b: TranslationVersion) -> S.CompareOut:
    sm = difflib.SequenceMatcher(None, a.target_text, b.target_text)
    changes = [{"op": op, "from": a.target_text[i1:i2], "to": b.target_text[j1:j2]} for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
    return S.CompareOut(translation_id=str(a.segment_id), a_version_id=str(a.id), b_version_id=str(b.id),
                        similarity_percent=int(round(sm.ratio() * 100)), changes=changes[:200])


# ---------------------------------------------------------------------------------- segmentation
_SENTENCE = re.compile(r"(?<=[.!?。！？])\s+")


def split_text(text: str, max_len: int = 1000) -> List[str]:
    """Paragraph-first segmentation; long paragraphs are split on sentence boundaries."""
    segments: List[str] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_len:
            segments.append(para)
            continue
        buf = ""
        for sentence in _SENTENCE.split(para):
            if buf and len(buf) + 1 + len(sentence) > max_len:
                segments.append(buf)
                buf = sentence
            else:
                buf = f"{buf} {sentence}".strip()
        while len(buf) > max_len:  # a single very long sentence: hard split
            segments.append(buf[:max_len])
            buf = buf[max_len:]
        if buf:
            segments.append(buf)
    return segments
