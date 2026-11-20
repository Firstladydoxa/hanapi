from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from ..seed import join_pilot
from .. import languages as languages_service
from ..config import get_settings
from ..database import get_db
from ..deps import client_ip, get_current_user, get_user_no_csrf
from ..errors import ApiError, not_found
from ..models import schemas as S
from ..models.db import (
    AuditEvent, Language, LanguageDirection, ModelDirectionScore, ModelRegistry, Project, ProjectDirection, ProjectMember,
    RoutingEvent, TerminologyEntry, UsageRecord, User,
)
from ..models.registry import invalidate_identifier_cache, list_models
from ..models.router import is_healthy, provider_error_rates
from ..security import auth as sec
from ..security.permissions import ADMIN_ROLES, AUDIT_ROLES, has_engine_access, parse_uuid, require_roles
from ..terminology import terminology as term_service

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _n(code: str) -> str:
    return code.strip().lower().replace("_", "-")


def admin_user(request: Request, user: User = Depends(get_current_user)) -> User:
    require_roles(user, *ADMIN_ROLES, ip=client_ip(request))
    return user


def admin_read(request: Request, user: User = Depends(get_user_no_csrf)) -> User:
    require_roles(user, *ADMIN_ROLES, ip=client_ip(request))
    return user


def engine_user(request: Request, user: User = Depends(get_current_user)) -> User:
    if not has_engine_access(user):
        audit.record("access.denied", actor=user, outcome="denied", object_type="engine_details", ip=client_ip(request))
        raise ApiError(403, "forbidden", "You do not have permission to do that.")
    return user


def engine_read(request: Request, user: User = Depends(get_user_no_csrf)) -> User:
    return engine_user(request, user)


def audit_read(request: Request, user: User = Depends(get_user_no_csrf)) -> User:
    require_roles(user, *AUDIT_ROLES, ip=client_ip(request))
    return user


def _user_out(u: User, generated: Optional[str] = None) -> S.AdminUserOut:
    return S.AdminUserOut(id=str(u.id), email=u.email, display_name=u.display_name, role=u.role, status=u.status,
                          engine_details_granted=u.engine_details_granted, created_at=u.created_at, generated_password=generated)


# ------------------------------------------------------------------ users
@router.get("/users", response_model=List[S.AdminUserOut])
def list_users(actor: User = Depends(admin_read), db: Session = Depends(get_db)):
    return [_user_out(u) for u in db.execute(select(User).order_by(User.email)).scalars()]


@router.post("/users", response_model=S.AdminUserOut, status_code=201)
def create_user(body: S.AdminUserCreate, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    if (body.role == "technical_admin" or body.engine_details_granted) and actor.role != "technical_admin":
        raise ApiError(403, "forbidden", "Only a technical administrator can grant technical access.")
    password = body.password or sec.generate_password()
    u = User(email=body.email.strip().lower(), display_name=body.display_name, role=body.role, password_hash=sec.hash_password(password),
             engine_details_granted=body.engine_details_granted)
    db.add(u)
    try:
        db.flush()
        join_pilot(db, u)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "already_exists", "A user with that email already exists.")
    audit.record("admin.user_created", actor=actor, object_type="user", object_id=u.id, details={"role": u.role}, ip=client_ip(request))
    return _user_out(u, None if body.password else password)


@router.patch("/users/{user_id}", response_model=S.AdminUserOut)
def patch_user(user_id: str, body: S.AdminUserPatch, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, parse_uuid(user_id, "user"))
    if u is None:
        raise not_found("user")
    data = body.model_dump(exclude_unset=True)
    if actor.role != "technical_admin" and (data.get("role") == "technical_admin" or u.role == "technical_admin"
                                            or "engine_details_granted" in data):
        raise ApiError(403, "forbidden", "Only a technical administrator can change technical access.")
    if u.id == actor.id and (data.get("status") == "disabled" or ("role" in data and data["role"] != actor.role)):
        raise ApiError(409, "self_change", "You cannot disable or change the role of your own account.")
    if "password" in data:
        u.password_hash = sec.hash_password(data.pop("password"))
    for k, v in data.items():
        setattr(u, k, v)
    db.commit()
    audit.record("admin.user_updated", actor=actor, object_type="user", object_id=u.id, details={"fields": sorted(body.model_dump(exclude_unset=True))},
                 ip=client_ip(request))
    return _user_out(u)


# ------------------------------------------------------------------ projects
def _project_out(p: Project) -> S.AdminProjectOut:
    return S.AdminProjectOut(id=str(p.id), name=p.name, client=p.client, domain=p.domain, style=p.style, instructions=p.instructions,
                             status=p.status, retention_days=p.retention_days, allow_external_processing=p.allow_external_processing,
                             pilot_opt_in=p.pilot_opt_in, monthly_char_quota=p.monthly_char_quota,
                             monthly_spend_limit=float(p.monthly_spend_limit) if p.monthly_spend_limit is not None else None,
                             spend_alert_pct=p.spend_alert_pct)


def _set_directions(db: Session, project: Project, directions: Optional[List[Dict[str, str]]]) -> None:
    if directions is None:
        return
    for row in db.execute(select(ProjectDirection).where(ProjectDirection.project_id == project.id)).scalars():
        db.delete(row)
    for d in directions:
        src, tgt = S._norm_lang(d.get("source_code", "")), S._norm_lang(d.get("target_code", ""))
        db.add(ProjectDirection(project_id=project.id, source_code=src, target_code=tgt))


@router.get("/projects", response_model=List[S.AdminProjectOut])
def list_projects(actor: User = Depends(admin_read), db: Session = Depends(get_db)):
    return [_project_out(p) for p in db.execute(select(Project).order_by(Project.name)).scalars()]


@router.post("/projects", response_model=S.AdminProjectOut, status_code=201)
def create_project(body: S.AdminProjectIn, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    data = body.model_dump(exclude={"directions"})
    p = Project(**data, owner_id=actor.id)
    db.add(p)
    db.flush()
    _set_directions(db, p, body.directions)
    db.commit()
    audit.record("admin.project_created", actor=actor, object_type="project", object_id=p.id, project_id=p.id, ip=client_ip(request))
    return _project_out(p)


@router.patch("/projects/{project_id}", response_model=S.AdminProjectOut)
def patch_project(project_id: str, body: S.AdminProjectPatch, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    p = db.get(Project, parse_uuid(project_id, "project"))
    if p is None:
        raise not_found("project")
    for k, v in body.model_dump(exclude_unset=True, exclude={"directions"}).items():
        setattr(p, k, v)
    if "directions" in body.model_fields_set:
        _set_directions(db, p, body.directions)
    db.commit()
    audit.record("admin.project_updated", actor=actor, object_type="project", object_id=p.id, project_id=p.id, ip=client_ip(request))
    return _project_out(p)


@router.get("/projects/{project_id}/members", response_model=List[S.MemberOut])
def get_members(project_id: str, actor: User = Depends(admin_read), db: Session = Depends(get_db)):
    pid = parse_uuid(project_id, "project")
    rows = db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id).where(ProjectMember.project_id == pid)
                      .order_by(User.email)).all()
    return [S.MemberOut(user_id=str(u.id), email=u.email, display_name=u.display_name, role=m.role, can_approve=m.can_approve) for m, u in rows]


@router.put("/projects/{project_id}/members", response_model=List[S.MemberOut])
def put_members(project_id: str, body: S.MembersPut, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    p = db.get(Project, parse_uuid(project_id, "project"))
    if p is None:
        raise not_found("project")
    wanted = {}
    for m in body.members:
        uid = parse_uuid(m.user_id, "user")
        if db.get(User, uid) is None:
            raise not_found("user")
        wanted[uid] = m
    for row in db.execute(select(ProjectMember).where(ProjectMember.project_id == p.id)).scalars():
        if row.user_id not in wanted:
            db.delete(row)
    existing = {r.user_id: r for r in db.execute(select(ProjectMember).where(ProjectMember.project_id == p.id)).scalars()}
    for uid, m in wanted.items():
        can = m.can_approve if m.can_approve is not None else m.role in ("translator", "reviewer")
        if uid in existing:
            existing[uid].role, existing[uid].can_approve = m.role, can
        else:
            db.add(ProjectMember(project_id=p.id, user_id=uid, role=m.role, can_approve=can))
    db.commit()
    audit.record("admin.members_updated", actor=actor, object_type="project", object_id=p.id, project_id=p.id,
                 details={"count": len(wanted)}, ip=client_ip(request))
    return get_members(project_id, actor, db)


# ------------------------------------------------------------------ terminology
def _term_out(e: TerminologyEntry) -> S.AdminTermOut:
    return S.AdminTermOut(term_id=str(e.id), source_term=e.source_term, target_term=e.target_term, definition=e.definition, domain=e.domain,
                          part_of_speech=e.part_of_speech, usage_note=e.usage_note,
                          forbidden=[str(x) for x in (e.forbidden_alternatives or [])], status=e.status,
                          project_id=str(e.project_id) if e.project_id else None, scope=e.scope, source_language=e.source_language,
                          target_language=e.target_language)


@router.get("/terminology", response_model=List[S.AdminTermOut])
def list_terms(project_id: Optional[str] = Query(None, max_length=64), status: Optional[str] = Query(None, max_length=16),
               actor: User = Depends(admin_read), db: Session = Depends(get_db), limit: int = Query(200, ge=1, le=1000)):
    stmt = select(TerminologyEntry).order_by(TerminologyEntry.source_term).limit(limit)
    if project_id:
        stmt = stmt.where(TerminologyEntry.project_id == parse_uuid(project_id, "project"))
    if status:
        stmt = stmt.where(TerminologyEntry.status == status)
    return [_term_out(e) for e in db.execute(stmt).scalars()]


@router.post("/terminology", response_model=S.AdminTermOut, status_code=201)
def create_term(body: S.TermIn, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    if (body.scope == "global") != (body.project_id is None):
        raise ApiError(422, "validation_error", "Global terms have no project; project terms need a project.")
    pid = None
    if body.project_id:
        pid = parse_uuid(body.project_id, "project")
        if db.get(Project, pid) is None:
            raise not_found("project")
    e = TerminologyEntry(project_id=pid, scope=body.scope, source_language=body.source_language, target_language=body.target_language,
                         source_term=body.source_term, target_term=body.target_term, definition=body.definition, domain=body.domain,
                         part_of_speech=body.part_of_speech, usage_note=body.usage_note, forbidden_alternatives=body.forbidden,
                         status=body.status, owner_id=actor.id)
    db.add(e)
    db.flush()
    term_service.record_status_change(db, e, actor.id, None, e.status, "created")
    db.commit()
    audit.record("admin.term_created", actor=actor, object_type="term", object_id=e.id, project_id=pid, ip=client_ip(request))
    return _term_out(e)


@router.patch("/terminology/{term_id}", response_model=S.AdminTermOut)
def patch_term(term_id: str, body: S.TermPatch, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    e = db.get(TerminologyEntry, parse_uuid(term_id, "term"))
    if e is None:
        raise not_found("term")
    data = body.model_dump(exclude_unset=True)
    comment = data.pop("comment", None)
    new_status = data.pop("status", None)
    if "forbidden" in data:
        e.forbidden_alternatives = data.pop("forbidden")
    for k, v in data.items():
        setattr(e, k, v)
    if new_status and new_status != e.status:
        term_service.record_status_change(db, e, actor.id, e.status, new_status, comment)
        e.status = new_status
    db.commit()
    audit.record("admin.term_updated", actor=actor, object_type="term", object_id=e.id, project_id=e.project_id, ip=client_ip(request))
    return _term_out(e)


# ------------------------------------------------------------------ language readiness
def _admin_direction(d: LanguageDirection) -> S.AdminDirectionOut:
    return S.AdminDirectionOut(source_code=d.source_code, target_code=d.target_code, readiness_tier=d.readiness_tier, review_note=d.review_note,
                               technical_status=d.technical_status, technical_checked_at=d.technical_checked_at,
                               technical_detail=d.technical_detail, validation_status=d.validation_status)


@router.get("/language-directions", response_model=List[S.AdminDirectionOut])
def admin_directions(actor: User = Depends(admin_read), db: Session = Depends(get_db)):
    rows = db.execute(select(LanguageDirection).order_by(LanguageDirection.source_code, LanguageDirection.target_code)).scalars()
    return [_admin_direction(d) for d in rows]


@router.put("/language-directions", response_model=List[S.AdminDirectionOut])
def put_directions(body: S.DirectionsPut, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    for d in body.directions:
        if db.get(Language, d.source_code) is None or db.get(Language, d.target_code) is None or d.source_code == d.target_code:
            raise ApiError(422, "unknown_language", f"Unknown or invalid language pair {d.source_code}->{d.target_code}.")
        row = db.get(LanguageDirection, (d.source_code, d.target_code))
        if row is None:
            row = LanguageDirection(source_code=d.source_code, target_code=d.target_code)
            db.add(row)
        row.readiness_tier, row.review_note, row.benchmark_ref, row.updated_by = d.readiness_tier, d.review_note, d.benchmark_ref, actor.id
    db.commit()
    audit.record("admin.readiness_updated", actor=actor, object_type="language_direction", details={"count": len(body.directions)},
                 ip=client_ip(request))
    return admin_directions(actor, db)


@router.post("/languages", response_model=S.LanguageOut, status_code=201)
def put_language(body: S.LanguagePut, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    row = db.get(Language, body.code) or Language(code=body.code, display_name=body.display_name)
    row.display_name, row.script, row.region, row.active = body.display_name, body.script, body.region, body.active
    db.add(row)
    db.commit()
    audit.record("admin.language_updated", actor=actor, object_type="language", object_id=body.code, ip=client_ip(request))
    return S.LanguageOut(code=row.code, display_name=row.display_name, script=row.script)


@router.put("/language-directions/validation", response_model=S.AdminDirectionOut)
def put_validation(body: S.DirectionValidationPut, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Record the outcome of the Stage-2 human evaluation. It does not change availability by itself."""
    row = db.get(LanguageDirection, (_n(body.source_code), _n(body.target_code)))
    if row is None:
        raise not_found("Language direction")
    row.validation_status, row.updated_by = body.validation_status, actor.id
    if body.note:
        row.review_note = body.note
    db.commit()
    audit.record("admin.direction_validation", actor=actor, object_type="language_direction", details={"status": body.validation_status},
                 ip=client_ip(request))
    return _admin_direction(row)


@router.post("/languages/enable-pilot")
def enable_pilot(body: S.PilotEnableIn, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Open technically verified English<->X directions for CONTROLLED TESTING only (never production)."""
    changed = languages_service.enable_pilot_directions(db, [_n(c) for c in body.codes] if body.codes is not None else None, actor.id)
    audit.record("admin.pilot_languages_enabled", actor=actor, object_type="language_direction", details={"directions": changed}, ip=client_ip(request))
    return {"directions_enabled": changed}


@router.post("/language-directions/test", response_model=S.DirectionTestOut)
def test_direction(body: S.DirectionTestIn, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Stage-1 check of one direction (works before it is enabled). Records the result; never reveals which engine answered."""
    from ..models.gateway import ModelGateway, QuotaExceeded, TranslationUnavailable
    from ..providers.base import degenerate_flag

    src, tgt = _n(body.source_code), _n(body.target_code)
    row = db.get(LanguageDirection, (src, tgt))
    if row is None:
        raise not_found("Language direction")
    project = db.execute(select(Project).where(Project.pilot_opt_in.is_(True), Project.allow_external_processing.is_(False))
                         .order_by(Project.created_at)).scalars().first()
    if project is None:
        raise ApiError(409, "no_test_project", "Create a pilot project to run language checks.")
    try:
        result = ModelGateway().translate(db, project, src, tgt, body.text, user_id=actor.id, technical_test=True)
        out, flag = result.text, degenerate_flag(result.text, body.text)
        status = "degraded" if flag else "passed"
    except (TranslationUnavailable, QuotaExceeded):
        out, flag, status = "", "unavailable", "failed"
    row.technical_status, row.technical_checked_at = status, datetime.now(timezone.utc)
    row.technical_detail = {"flag": flag, "probe": "admin check"}
    db.commit()
    audit.record("admin.direction_tested", actor=actor, object_type="language_direction", details={"status": status}, ip=client_ip(request))
    return S.DirectionTestOut(source_code=src, target_code=tgt, output=out, flag=flag, technical_status=status)


@router.get("/models/language-codes")
def engine_language_codes(actor: User = Depends(engine_read), db: Session = Depends(get_db)):
    """ENGINE-PROTECTED: each language's engine-specific token. Only users with engine-details permission may read this."""
    return [{"code": l.code, "model_codes": l.model_codes} for l in db.execute(select(Language).order_by(Language.code)).scalars()]


# ------------------------------------------------------------------ audit
@router.get("/audit-events", response_model=List[S.AuditEventOut])
def audit_events(action: Optional[str] = Query(None, max_length=64), project_id: Optional[str] = Query(None, max_length=64),
                 actor_id: Optional[str] = Query(None, max_length=64), limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
                 actor: User = Depends(audit_read), db: Session = Depends(get_db)):
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if project_id:
        stmt = stmt.where(AuditEvent.project_id == parse_uuid(project_id, "project"))
    if actor_id:
        stmt = stmt.where(AuditEvent.actor_id == parse_uuid(actor_id, "user"))
    return [S.AuditEventOut(id=str(e.id), actor_id=str(e.actor_id) if e.actor_id else None, actor_role=e.actor_role,
                            project_id=str(e.project_id) if e.project_id else None, action=e.action, object_type=e.object_type,
                            object_id=e.object_id, outcome=e.outcome, request_id=e.request_id, created_at=e.created_at, details=e.details)
            for e in db.execute(stmt).scalars()]


# ------------------------------------------------------------------ protected engine operations (INTERNAL schemas live here)
class EngineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    provider: str
    model_name: Optional[str] = None
    revision: Optional[str] = None
    license: Optional[str] = None
    license_cleared: bool
    license_evidence: Optional[str] = None
    runtime: Optional[str] = None
    is_external: bool
    enabled: bool
    deployment_status: str
    languages: Optional[Any] = None
    max_chars: int
    cost_per_1k_chars: float
    avg_latency_ms: int
    priority: int
    notes: Optional[str] = None
    healthy: Optional[bool] = None


class EnginePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Optional[bool] = None
    license_cleared: Optional[bool] = None
    license_evidence: Optional[str] = None
    license: Optional[str] = None
    revision: Optional[str] = None
    deployment_status: Optional[str] = None
    languages: Optional[List[str]] = None
    max_chars: Optional[int] = None
    cost_per_1k_chars: Optional[float] = None
    avg_latency_ms: Optional[int] = None
    priority: Optional[int] = None
    notes: Optional[str] = None
    benchmark_scores: Optional[List[Dict[str, Any]]] = None


@router.get("/models", response_model=List[EngineOut])
def get_models(actor: User = Depends(engine_read), db: Session = Depends(get_db)):
    rates = provider_error_rates(db)
    out = []
    for m in list_models(db):
        item = EngineOut.model_validate(m)
        item.healthy = is_healthy(rates, m.key)
        out.append(item)
    return out


@router.patch("/models/{key}", response_model=EngineOut)
def patch_model(key: str, body: EnginePatch, request: Request, actor: User = Depends(engine_user), db: Session = Depends(get_db)):
    m = db.get(ModelRegistry, key)
    if m is None:
        raise not_found("model")
    data = body.model_dump(exclude_unset=True)
    scores = data.pop("benchmark_scores", None)
    if data.get("deployment_status") not in (None, "not_deployed", "deployed", "degraded", "retired"):
        raise ApiError(422, "validation_error", "Invalid deployment status.")
    for k, v in data.items():
        setattr(m, k, v)
    if m.license_cleared and not (m.license_evidence or "").strip():
        db.rollback()
        raise ApiError(422, "license_evidence_required", "Record the licence evidence before marking a model as licence-cleared.")
    for s in scores or []:
        src, tgt = S._norm_lang(str(s.get("source_code"))), S._norm_lang(str(s.get("target_code")))
        row = db.get(ModelDirectionScore, (m.key, src, tgt)) or ModelDirectionScore(model_key=m.key, source_code=src, target_code=tgt)
        row.benchmark_score = s.get("benchmark_score")
        row.notes = s.get("notes")
        db.add(row)
    db.commit()
    invalidate_identifier_cache()
    audit.record("admin.model_updated", actor=actor, object_type="model_registry", object_id=m.key,
                 details={"fields": sorted(body.model_dump(exclude_unset=True))}, ip=client_ip(request))
    return EngineOut.model_validate(m)


@router.get("/routing-events")
def routing_events(project_id: Optional[str] = Query(None, max_length=64), status: Optional[str] = Query(None, max_length=16),
                   limit: int = Query(100, ge=1, le=500), actor: User = Depends(engine_read), db: Session = Depends(get_db)):
    stmt = select(RoutingEvent).order_by(RoutingEvent.created_at.desc()).limit(limit)
    if project_id:
        stmt = stmt.where(RoutingEvent.project_id == parse_uuid(project_id, "project"))
    if status:
        stmt = stmt.where(RoutingEvent.status == status)
    return [{"id": str(e.id), "request_id": e.request_id, "project_id": str(e.project_id) if e.project_id else None,
             "segment_id": str(e.segment_id) if e.segment_id else None, "version_id": str(e.version_id) if e.version_id else None,
             "source_code": e.source_code, "target_code": e.target_code, "attempt_no": e.attempt_no, "model_key": e.model_key,
             "status": e.status, "error_category": e.error_category, "latency_ms": e.latency_ms, "estimated_cost": e.estimated_cost,
             "chars": e.chars, "route_reason": e.route_reason, "fallback": e.fallback, "created_at": e.created_at.isoformat()}
            for e in db.execute(stmt).scalars()]


@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=365), actor: User = Depends(engine_read), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(UsageRecord.project_id, UsageRecord.model_key, UsageRecord.source_code, UsageRecord.target_code, func.count(),
               func.count().filter(UsageRecord.success.is_(False)), func.coalesce(func.sum(UsageRecord.chars), 0),
               func.coalesce(func.sum(UsageRecord.cost), 0.0), func.coalesce(func.avg(UsageRecord.latency_ms), 0))
        .where(UsageRecord.created_at >= since).group_by(UsageRecord.project_id, UsageRecord.model_key, UsageRecord.source_code,
                                                          UsageRecord.target_code)).all()
    return {"since": since.isoformat(), "rows": [
        {"project_id": str(p), "model_key": mk, "source_code": s, "target_code": t, "requests": n, "errors": err, "chars": int(ch),
         "cost": float(c), "avg_latency_ms": int(lat)} for p, mk, s, t, n, err, ch, c, lat in rows]}


@router.get("/health")
def health(actor: User = Depends(engine_read), db: Session = Depends(get_db)):
    from ..models.registry import adapter_for

    rates = provider_error_rates(db)
    models = []
    for m in list_models(db):
        a = adapter_for(m)
        attempts, failures = rates.get(m.key, (0, 0))
        models.append({"key": m.key, "enabled": m.enabled, "deployment_status": m.deployment_status, "adapter_configured": bool(a and a.configured()),
                       "recent_attempts": attempts, "recent_failures": failures, "healthy": is_healthy(rates, m.key)})
    db.execute(select(1))
    return {"database": "ok", "jobs_eager": get_settings().jobs_eager, "models": models}
