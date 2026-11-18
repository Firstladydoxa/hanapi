"""Authorisation helpers. The backend is the control; the UI only mirrors it."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import ApiError, forbidden, not_found
from ..models.db import Project, ProjectMember, Segment, User

APPROVER_MEMBER_ROLES = {"translator", "reviewer"}
ADMIN_ROLES = {"tni_admin", "technical_admin"}
AUDIT_ROLES = {"auditor", "tni_admin", "technical_admin"}


def parse_uuid(value: object, what: str = "resource") -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise not_found(what)


def get_membership(db: Session, user: User, project_id: object, ip: Optional[str] = None) -> Tuple[Project, ProjectMember]:
    """Project + membership, or 404 (existence of other projects is never revealed)."""
    pid = parse_uuid(project_id, "project")
    row = db.execute(
        select(Project, ProjectMember)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(Project.id == pid, ProjectMember.user_id == user.id, Project.status == "active")
    ).first()
    if row is None:
        audit.record("access.denied", actor=user, outcome="denied", object_type="project", object_id=str(pid), ip=ip)
        raise not_found("project")
    return row[0], row[1]


def effective_can_approve(member: ProjectMember) -> bool:
    return bool(member.can_approve) and member.role in APPROVER_MEMBER_ROLES


def segment_visible(member: ProjectMember, segment: Segment, user: User) -> bool:
    """Translators see their own work; reviewers and project managers see all work in the project."""
    if member.role in ("reviewer", "project_manager"):
        return True
    return segment.created_by == user.id


def load_segment(db: Session, user: User, segment_id: object, ip: Optional[str] = None, for_update: bool = False):
    sid = parse_uuid(segment_id, "translation")
    stmt = select(Segment).where(Segment.id == sid)
    if for_update:
        stmt = stmt.with_for_update()
    segment = db.execute(stmt).scalar_one_or_none()
    if segment is None:
        raise not_found("translation")
    member = db.execute(
        select(ProjectMember)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(ProjectMember.project_id == segment.project_id, ProjectMember.user_id == user.id, Project.status == "active")
    ).scalar_one_or_none()
    if member is None or not segment_visible(member, segment, user):
        audit.record("access.denied", actor=user, outcome="denied", object_type="translation", object_id=str(sid), ip=ip)
        raise not_found("translation")
    return segment, member


def has_engine_access(user: User) -> bool:
    return user.role == "technical_admin" or (user.role == "tni_admin" and bool(user.engine_details_granted))


def require_roles(user: User, *roles: str, ip: Optional[str] = None) -> None:
    if user.role not in roles:
        audit.record("access.denied", actor=user, outcome="denied", object_type="admin", details={"need": list(roles)}, ip=ip)
        raise forbidden()


@dataclass(frozen=True)
class HumanActor:
    """Proof that the request came from an authenticated human session with a valid CSRF token.

    Only `deps.get_human_actor` creates instances. Orchestrator / tool code never has one, so
    it structurally cannot call the approval service.
    """

    user: User
    session_id: str
    csrf_verified: bool

    @classmethod
    def _issue(cls, user: User, session_id: str) -> "HumanActor":
        return cls(user=user, session_id=session_id, csrf_verified=True)


def assert_human(actor: object) -> HumanActor:
    if not isinstance(actor, HumanActor) or not actor.csrf_verified:
        raise ApiError(403, "human_approval_required", "Approval must be performed by a signed-in person.")
    return actor
