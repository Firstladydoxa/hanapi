from __future__ import annotations

import logging
import threading
import uuid
from typing import List

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, services
from ..config import get_settings
from ..database import get_db
from ..deps import client_ip, get_current_user
from ..errors import ApiError
from ..jobs.tasks import process_job, process_job_task
from ..models import schemas as S
from ..models.db import ProjectMember, Segment, TranslationJob, User
from ..qa.runner import run_all
from ..ratelimit import enforce
from ..security import serializers as ser
from ..security.permissions import get_membership, parse_uuid
from ..terminology import terminology as term_service

log = logging.getLogger("han.jobs")
router = APIRouter(prefix="/v1", tags=["jobs"])
DONE_STATES = ("draft", "in_review", "approved", "rejected")


def _job_visible(member: ProjectMember, job: TranslationJob, user: User) -> bool:
    return member.role in ("reviewer", "project_manager") or job.requester_id == user.id


def _progress(db: Session, job_id: uuid.UUID) -> S.JobProgress:
    total, done, approved = db.execute(
        select(func.count(), func.count().filter(Segment.status.in_(DONE_STATES)), func.count().filter(Segment.status == "approved"))
        .where(Segment.job_id == job_id)).one()
    return S.JobProgress(total=total, done=done, approved=approved)


def _load_job(db: Session, user: User, job_id: str):
    job = db.get(TranslationJob, parse_uuid(job_id, "translation job"))
    if job is None:
        raise ApiError(404, "not_found", "The requested translation job was not found.")
    row = db.execute(select(ProjectMember).where(ProjectMember.project_id == job.project_id, ProjectMember.user_id == user.id)).scalar_one_or_none()
    if row is None or not _job_visible(row, job, user):
        audit.record("access.denied", actor=user, outcome="denied", object_type="job", object_id=job.id)
        raise ApiError(404, "not_found", "The requested translation job was not found.")
    return job


@router.post("/translation-jobs", response_model=S.JobCreated, status_code=201)
def create_job(body: S.JobRequest, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = get_settings()
    enforce("translate", str(user.id), s.rate_limit_translate_per_min)
    project, _m = get_membership(db, user, body.project_id, ip=client_ip(request))
    services.ensure_direction_allowed(db, project, body.source_language, body.target_language)
    if (body.text is None) == (body.segments is None):
        raise ApiError(422, "validation_error", "Provide either text or segments.")
    parts = [p.strip() for p in body.segments if p.strip()] if body.segments is not None else services.split_text(body.text or "")
    if not parts:
        raise ApiError(422, "empty_job", "There is no text to translate.")
    if len(parts) > s.max_job_segments or sum(len(p) for p in parts) > s.max_job_chars:
        raise ApiError(422, "job_too_large", "This job is too large. Please split it into smaller parts.")
    job = TranslationJob(project_id=project.id, requester_id=user.id, title=body.title, source_language=body.source_language,
                         target_language=body.target_language, input_type="text" if body.text is not None else "segments",
                         status="queued", options=body.options)
    db.add(job)
    db.flush()
    for i, text in enumerate(parts, start=1):
        db.add(Segment(project_id=project.id, job_id=job.id, sequence=i, source_language=body.source_language,
                       target_language=body.target_language, source_text=text, domain=project.domain, status="not_started", created_by=user.id))
    db.commit()
    audit.record("job.created", actor=user, object_type="job", object_id=job.id, project_id=project.id, details={"segments": len(parts)})
    if s.jobs_eager:
        process_job(str(job.id))
    elif s.jobs_background:
        threading.Thread(target=process_job, args=(str(job.id),), name=f"han-job-{job.id}", daemon=True).start()
    else:
        try:
            process_job_task.delay(str(job.id))
        except Exception:
            log.exception("job dispatch failed")
            job.status = "failed"
            db.commit()
            raise ApiError(503, "translation_unavailable", "I'm sorry, I couldn't start this job at the moment. Please try again shortly.")
    db.refresh(job)
    return S.JobCreated(job_id=str(job.id), status=job.status, segment_count=len(parts))


@router.get("/translation-jobs", response_model=List[S.JobSummary])
def list_jobs(project_id: str = Query(max_length=64), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, member = get_membership(db, user, project_id)
    stmt = select(TranslationJob).where(TranslationJob.project_id == project.id).order_by(TranslationJob.created_at.desc()).limit(100)
    if member.role == "translator":
        stmt = stmt.where(TranslationJob.requester_id == user.id)
    return [S.JobSummary(job_id=str(j.id), title=j.title, source_language=j.source_language, target_language=j.target_language,
                         status=j.status, progress=_progress(db, j.id), created_at=j.created_at) for j in db.execute(stmt).scalars()]


@router.get("/translation-jobs/{job_id}", response_model=S.JobOut)
def get_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = _load_job(db, user, job_id)
    segments = list(db.execute(select(Segment).where(Segment.job_id == job.id).order_by(Segment.sequence)).scalars())
    terms = term_service.search(db, job.project_id, job.source_language, job.target_language, limit=2000)
    out: List[S.JobSegmentOut] = []
    for seg in segments:
        ver = services.latest_version(db, seg.id)
        warnings = []
        if ver is not None:
            seg_terms = [t for t in terms if term_service.contains_term(seg.source_text, t.source_term)]
            warnings = ser.warnings_out(run_all(db, job.project_id, seg.source_text, ver.target_text, seg.source_language,
                                                seg.target_language, terms=seg_terms))
        out.append(S.JobSegmentOut(segment_id=str(seg.id), sequence=seg.sequence, source_text=seg.source_text, status=seg.status,
                                   current_version=ser.version_out(db, ver) if ver else None, warnings=warnings))
    return S.JobOut(job_id=str(job.id), project_id=str(job.project_id), title=job.title, source_language=job.source_language,
                    target_language=job.target_language, status=job.status, progress=_progress(db, job.id), segments=out)
