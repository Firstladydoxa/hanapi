"""Response whitelisting: ORM rows -> PUBLIC schemas. Primary control for engine confidentiality.

Only fields explicitly mapped here can reach a translator. This module deliberately has no import of
`models.internal_schemas`, `models.registry`, `models.router` or the gateway.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import schemas as S
from ..models.db import Approval, LanguageDirection, Project, ProjectMember, Segment, TranslationVersion, User


def user_out(u: User) -> S.UserOut:
    return S.UserOut(id=str(u.id), email=u.email, display_name=u.display_name, role=u.role, status=u.status)


def direction_out(d: LanguageDirection) -> S.DirectionOut:
    return S.DirectionOut(source_code=d.source_code, target_code=d.target_code, readiness_tier=d.readiness_tier, review_note=d.review_note)


def warnings_out(items: Iterable[Dict[str, Any]]) -> List[S.WarningOut]:
    return [S.WarningOut(type=w["type"], severity=w["severity"], message=w["message"], span=w.get("span")) for w in items]


def versions_out(db: Session, versions: Sequence[TranslationVersion]) -> List[S.VersionOut]:
    if not versions:
        return []
    ids = [v.id for v in versions]
    approvals = {a.version_id: a for a in db.execute(select(Approval).where(Approval.version_id.in_(ids))).scalars()}
    user_ids = {v.created_by for v in versions} | {a.approver_id for a in approvals.values()}
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars()}

    def ref(uid) -> S.UserRef:
        u = users.get(uid)
        return S.UserRef(id=str(uid), display_name=u.display_name if u else "Unknown")

    out: List[S.VersionOut] = []
    for v in versions:
        a: Optional[Approval] = approvals.get(v.id)
        out.append(
            S.VersionOut(
                version_id=str(v.id),
                version_number=v.version_number,
                target_text=v.target_text,
                origin=v.origin,  # type: ignore[arg-type]
                created_by=ref(v.created_by),
                created_at=v.created_at,
                parent_version_id=str(v.parent_version_id) if v.parent_version_id else None,
                change_note=v.change_note,
                approval_state=a.decision if a else "unapproved",  # type: ignore[arg-type]
                approval=S.ApprovalOut(approver=ref(a.approver_id), decision=a.decision, comment=a.comment, created_at=a.created_at)  # type: ignore[arg-type]
                if a
                else None,
            )
        )
    return out


def version_out(db: Session, version: TranslationVersion) -> S.VersionOut:
    return versions_out(db, [version])[0]


def translation_out(db: Session, seg: Segment, versions: Sequence[TranslationVersion]) -> S.TranslationOut:
    vs = versions_out(db, versions)
    return S.TranslationOut(
        translation_id=str(seg.id),
        project_id=str(seg.project_id),
        source_language=seg.source_language,
        target_language=seg.target_language,
        source_text=seg.source_text,
        context=seg.context,
        status=seg.status,
        versions=vs,
        current_version_id=vs[-1].version_id if vs else None,
    )


def project_list_item(p: Project, m: ProjectMember) -> S.ProjectListItem:
    return S.ProjectListItem(id=str(p.id), name=p.name, domain=p.domain, style=p.style, member_role=m.role)
