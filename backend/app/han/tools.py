"""HAN's tool registry (spec §8.3).

There is deliberately NO approval tool: approval is an explicit, authenticated human action
(`POST /v1/versions/{id}/approve`, which needs a `HumanActor`). `save_approved_translation` is the
promotion step that runs only after an approval row already exists, and it verifies that.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import ApiError, not_found
from ..memory import translation_memory as tm
from ..models import schemas as S
from ..models.db import Approval, Project, ProjectMember, Segment, TranslationVersion, User
from ..qa.runner import run_all
from ..security import serializers as ser
from ..security.permissions import get_membership, load_segment
from ..terminology import terminology as term_service


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., Any]
    permission: str


def translate(db: Session, user: User, project_id: object, source: str, target: str, text: str, context: Optional[str] = None,
              domain: Optional[str] = None) -> S.TranslateResponse:
    from .. import services

    project, _ = get_membership(db, user, project_id)
    seg, ver, warnings, matches, terms, note = services.create_draft(db, user, project, source, target, text, context=context,
                                                                      domain=domain, workflow="chat")
    return services.translate_response(seg, ver, warnings, matches, terms, note)


def search_translation_memory(db: Session, user: User, project_id: object, source: str, target: str, query: str) -> List[S.TMResult]:
    project, _ = get_membership(db, user, project_id)
    out = []
    for m in tm.search(db, project.id, source, target, query, min_match=get_settings().tm_min_match):
        out.append(S.TMResult(tm_id=str(m.tm_id), source_text=m.source_text, target_text=m.target_text, match_percent=m.match_percent,
                              match_type=m.match_type, approved_at=m.approved_at,  # type: ignore[arg-type]
                              provenance={"project_id": str(m.project_id), "version_id": str(m.version_id)}))
    return out


def search_terminology(db: Session, user: User, project_id: object, source: str, target: str, query: str = "") -> List[S.TermResult]:
    project, _ = get_membership(db, user, project_id)
    return [term_result(e) for e in term_service.search(db, project.id, source, target, query)]


def term_result(e) -> S.TermResult:
    return S.TermResult(term_id=str(e.id), source_term=e.source_term, target_term=e.target_term, definition=e.definition, domain=e.domain,
                        part_of_speech=e.part_of_speech, usage_note=e.usage_note,
                        forbidden=[str(x) for x in (e.forbidden_alternatives or [])], status=e.status)


def check_translation(db: Session, user: User, project_id: object, source_text: str, target_text: str, source: str, target: str) -> List[S.WarningOut]:
    project, _ = get_membership(db, user, project_id)
    return ser.warnings_out(run_all(db, project.id, source_text, target_text, source, target))


def compare_translations(db: Session, user: User, segment_id: object, a_version_id: object, b_version_id: object) -> S.CompareOut:
    from .. import services

    seg, _ = load_segment(db, user, segment_id)
    vs = {str(v.id): v for v in services.list_versions(db, seg.id)}
    a, b = vs.get(str(a_version_id)), vs.get(str(b_version_id))
    if a is None or b is None:
        raise not_found("translation version")
    return services.compare_versions(a, b)


def save_translation_draft(db: Session, user: User, segment_id: object, target_text: str, parent_version_id: object,
                           change_note: Optional[str] = None) -> TranslationVersion:
    from .. import services

    seg, _ = load_segment(db, user, segment_id, for_update=True)
    return services.save_version(db, user, seg, target_text, parent_version_id, change_note, workflow="tool")


def save_approved_translation(db: Session, approval_id: object) -> tm.TranslationMemory:  # type: ignore[name-defined]
    """Promote to approved TM. Refuses unless an `approved` approval row already exists for the version."""
    approval = db.get(Approval, approval_id if isinstance(approval_id, uuid.UUID) else uuid.UUID(str(approval_id)))
    if approval is None or approval.decision != "approved":
        raise ApiError(409, "approval_required", "Only a human-approved translation can be added to the Translation Memory.")
    version = db.get(TranslationVersion, approval.version_id)
    segment = db.get(Segment, version.segment_id)
    entry = tm.promote(db, approval, version, segment)
    if entry is None:
        raise ApiError(409, "approval_required", "Only a human-approved translation can be added to the Translation Memory.")
    return entry


# The registry exposes exactly these capabilities to the orchestrator. Adding an approve tool here is a
# bug: tests assert no tool name contains "approve" other than the post-approval promotion step.
TOOLS: Dict[str, ToolSpec] = {t.name: t for t in [
    ToolSpec("translate", "Create a translation draft", translate, "project member"),
    ToolSpec("search_translation_memory", "Find approved TM matches", search_translation_memory, "project member"),
    ToolSpec("search_terminology", "Retrieve approved terminology", search_terminology, "project member"),
    ToolSpec("check_translation", "Run QA checks", check_translation, "project member"),
    ToolSpec("compare_translations", "Compare two versions of a translation", compare_translations, "project member (own work or reviewer)"),
    ToolSpec("save_translation_draft", "Save a new immutable draft version", save_translation_draft, "project member (own work or reviewer)"),
    ToolSpec("save_approved_translation", "Promote an already-approved version to TM (requires an approval row)",
             save_approved_translation, "internal: invoked by the human approval workflow"),
]}
ORCHESTRATOR_TOOLS = ("translate", "search_translation_memory", "search_terminology", "check_translation", "compare_translations")
