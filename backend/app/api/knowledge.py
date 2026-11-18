"""Knowledge-base governance. Only TNI/technical administrators manage it; content reaches translators only once a version is approved."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, knowledge
from ..database import get_db
from ..deps import client_ip
from ..errors import ApiError, not_found
from ..models import schemas as S
from ..models.db import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion, Project, User
from ..models.db import KNOWLEDGE_CATEGORIES
from ..security.permissions import parse_uuid
from .admin import admin_read, admin_user

router = APIRouter(prefix="/v1/admin/knowledge", tags=["knowledge"])
MAX_UPLOAD = 5 * 1024 * 1024
ROLES = {"translator", "reviewer", "project_manager", "tni_admin", "technical_admin", "auditor"}


class DocIn(S.Req):
    title: str = Field(min_length=1, max_length=300)
    category: str = Field(max_length=32)
    text: str = Field(min_length=1, max_length=2_000_000)
    languages: List[str] = []
    audience_roles: List[str] = []
    project_id: Optional[str] = Field(default=None, max_length=64)
    note: Optional[str] = Field(default=None, max_length=500)


class VersionIn(S.Req):
    text: str = Field(min_length=1, max_length=2_000_000)
    note: Optional[str] = Field(default=None, max_length=500)


class DocPatch(S.Req):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    category: Optional[str] = Field(default=None, max_length=32)
    languages: Optional[List[str]] = None
    audience_roles: Optional[List[str]] = None
    project_id: Optional[str] = Field(default=None, max_length=64)


class VersionOut(S.Public):
    id: str
    version_number: int
    filename: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
    approved_at: Optional[datetime] = None
    is_active: bool = False
    preview: Optional[str] = None
    text: Optional[str] = None


class DocOut(S.Public):
    id: str
    title: str
    category: str
    status: str
    languages: List[str] = []
    audience_roles: List[str] = []
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    system_managed: bool = False
    version_count: int = 0
    chunk_count: int = 0
    approved_version: Optional[int] = None
    updated_at: datetime


class DocDetail(DocOut):
    versions: List[VersionOut]


def _clean(db: Session, categories: Optional[str], languages: Optional[List[str]], roles: Optional[List[str]], project_id: Optional[str]):
    if categories is not None and categories not in KNOWLEDGE_CATEGORIES:
        raise ApiError(422, "invalid_category", "Unknown knowledge category.")
    bad = [r for r in (roles or []) if r not in ROLES]
    if bad:
        raise ApiError(422, "invalid_role", "Unknown audience role.")
    pid = None
    if project_id:
        pid = parse_uuid(project_id, "project")
        if db.get(Project, pid) is None:
            raise not_found("project")
    return [l.strip().lower().replace("_", "-") for l in (languages or []) if l.strip()], pid


def _doc_out(db: Session, d: KnowledgeDocument) -> DocOut:
    vc = db.execute(select(func.count()).select_from(KnowledgeVersion).where(KnowledgeVersion.document_id == d.id)).scalar() or 0
    cc = db.execute(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.document_id == d.id)).scalar() or 0
    av = db.get(KnowledgeVersion, d.approved_version_id) if d.approved_version_id else None
    pn = db.get(Project, d.project_id).name if d.project_id else None
    return DocOut(id=str(d.id), title=d.title, category=d.category, status=d.status, languages=d.languages or [], audience_roles=d.audience_roles or [],
                  project_id=str(d.project_id) if d.project_id else None, project_name=pn, system_managed=d.system_managed, version_count=vc,
                  chunk_count=cc, approved_version=av.version_number if av else None, updated_at=d.updated_at)


def _version_out(v: KnowledgeVersion, d: KnowledgeDocument, full: bool = False) -> VersionOut:
    return VersionOut(id=str(v.id), version_number=v.version_number, filename=v.filename, note=v.note, created_at=v.created_at, approved_at=v.approved_at,
                      is_active=d.approved_version_id == v.id and d.status == "approved", preview=v.text[:240], text=v.text if full else None)


def _detail(db: Session, d: KnowledgeDocument) -> DocDetail:
    vs = list(db.execute(select(KnowledgeVersion).where(KnowledgeVersion.document_id == d.id).order_by(KnowledgeVersion.version_number.desc())).scalars())
    return DocDetail(**_doc_out(db, d).model_dump(), versions=[_version_out(v, d, full=True) for v in vs])


def _doc(db: Session, doc_id: str) -> KnowledgeDocument:
    d = db.get(KnowledgeDocument, parse_uuid(doc_id, "document"))
    if d is None:
        raise not_found("document")
    return d


def _unprotected(d: KnowledgeDocument) -> None:
    if d.system_managed:
        raise ApiError(409, "system_managed", "This document ships with HAN and is managed by the platform.")


@router.get("/categories")
def categories(_: User = Depends(admin_read)):
    return {"categories": list(KNOWLEDGE_CATEGORIES), "roles": sorted(ROLES)}


@router.get("/documents", response_model=List[DocOut])
def list_documents(status: Optional[str] = None, category: Optional[str] = None, _: User = Depends(admin_read), db: Session = Depends(get_db)):
    stmt = select(KnowledgeDocument)
    if status:
        stmt = stmt.where(KnowledgeDocument.status == status)
    if category:
        stmt = stmt.where(KnowledgeDocument.category == category)
    return [_doc_out(db, d) for d in db.execute(stmt.order_by(KnowledgeDocument.updated_at.desc())).scalars()]


@router.get("/documents/{doc_id}", response_model=DocDetail)
def get_document(doc_id: str, _: User = Depends(admin_read), db: Session = Depends(get_db)):
    return _detail(db, _doc(db, doc_id))


@router.post("/documents", response_model=DocDetail, status_code=201)
def create_document(body: DocIn, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    langs, pid = _clean(db, body.category, body.languages, body.audience_roles, body.project_id)
    d = knowledge.create_document(db, actor, title=body.title, category=body.category, text=body.text, languages=langs,
                                  audience_roles=body.audience_roles, project_id=pid, note=body.note)
    audit.record("knowledge.created", actor=actor, object_type="knowledge_document", object_id=d.id, project_id=pid,
                 details={"category": d.category}, ip=client_ip(request))
    return _detail(db, d)


@router.post("/documents/upload", response_model=DocDetail, status_code=201)
async def upload_document(request: Request, file: UploadFile = File(...), title: str = Form(..., max_length=300), category: str = Form(..., max_length=32),
                          languages: str = Form(default="", max_length=500), audience_roles: str = Form(default="", max_length=500),
                          project_id: Optional[str] = Form(default=None, max_length=64), actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ApiError(413, "file_too_large", "That file is larger than 5 MB.")
    text = knowledge.extract_text(file.filename or "", data)
    langs, pid = _clean(db, category, [x for x in languages.split(",")], [x.strip() for x in audience_roles.split(",") if x.strip()], project_id or None)
    d = knowledge.create_document(db, actor, title=title, category=category, text=text, filename=(file.filename or "")[:300], languages=langs,
                                  audience_roles=[x.strip() for x in audience_roles.split(",") if x.strip()], project_id=pid)
    audit.record("knowledge.created", actor=actor, object_type="knowledge_document", object_id=d.id, project_id=pid,
                 details={"category": d.category, "upload": True}, ip=client_ip(request))
    return _detail(db, d)


@router.patch("/documents/{doc_id}", response_model=DocDetail)
def patch_document(doc_id: str, body: DocPatch, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    d = _doc(db, doc_id)
    _unprotected(d)
    langs, pid = _clean(db, body.category, body.languages, body.audience_roles, body.project_id)
    fields = body.model_fields_set
    if body.title is not None:
        d.title = body.title.strip()
    if body.category is not None:
        d.category = body.category
    if body.languages is not None:
        d.languages = langs
    if body.audience_roles is not None:
        d.audience_roles = body.audience_roles
    if "project_id" in fields:
        d.project_id = pid
    db.commit()
    audit.record("knowledge.updated", actor=actor, object_type="knowledge_document", object_id=d.id, ip=client_ip(request))
    return _detail(db, d)


@router.post("/documents/{doc_id}/versions", response_model=DocDetail, status_code=201)
def add_version(doc_id: str, body: VersionIn, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    d = _doc(db, doc_id)
    _unprotected(d)
    v = knowledge.add_version(db, d, actor, body.text, None, body.note)
    audit.record("knowledge.version_added", actor=actor, object_type="knowledge_document", object_id=d.id, details={"version": v.version_number},
                 ip=client_ip(request))
    return _detail(db, d)


@router.post("/documents/{doc_id}/versions/{version_id}/approve", response_model=DocDetail)
def approve(doc_id: str, version_id: str, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    d = _doc(db, doc_id)
    _unprotected(d)
    v = db.get(KnowledgeVersion, parse_uuid(version_id, "version"))
    if v is None or v.document_id != d.id:
        raise not_found("version")
    chunks = knowledge.approve_version(db, d, v, actor)
    audit.record("knowledge.approved", actor=actor, object_type="knowledge_document", object_id=d.id,
                 details={"version": v.version_number, "chunks": chunks}, ip=client_ip(request))
    return _detail(db, d)


@router.post("/documents/{doc_id}/deactivate", response_model=DocDetail)
def deactivate(doc_id: str, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    d = _doc(db, doc_id)
    _unprotected(d)
    knowledge.deactivate(db, d)
    audit.record("knowledge.deactivated", actor=actor, object_type="knowledge_document", object_id=d.id, ip=client_ip(request))
    return _detail(db, d)


@router.post("/reindex")
def reindex(request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    n = knowledge.reindex_missing_embeddings(db)
    audit.record("knowledge.reindexed", actor=actor, object_type="knowledge", details={"chunks": n}, ip=client_ip(request))
    return {"indexed": n}
