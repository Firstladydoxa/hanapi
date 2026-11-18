"""Document / batch translation jobs. Each segment becomes a draft version; failures mark the segment
`needs_attention` instead of failing the whole job (spec §4.3: translate in manageable batches)."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from .. import audit, services
from ..database import SessionLocal
from ..errors import ApiError
from ..models.db import Project, Segment, TranslationJob, User
from .celery_app import celery_app

log = logging.getLogger("han.jobs")


def process_job(job_id: str) -> str:
    """Translate every not-started segment of a job. Idempotent: already drafted segments are skipped."""
    jid = uuid.UUID(job_id)
    with SessionLocal() as db:
        job = db.get(TranslationJob, jid)
        if job is None:
            return "missing"
        project = db.get(Project, job.project_id)
        user = db.get(User, job.requester_id)
        job.status = "processing"
        db.commit()
        segments = list(db.execute(select(Segment).where(Segment.job_id == jid, Segment.status == "not_started")
                                   .order_by(Segment.sequence)).scalars())
        ok = failed = 0
        for seg in segments:
            try:
                services.generate_into_segment(db, user, project, seg)
                ok += 1
            except ApiError as e:
                db.rollback()
                seg = db.get(Segment, seg.id)
                seg.status = "needs_attention"
                db.commit()
                failed += 1
                if e.code in ("quota_exceeded", "direction_unsupported"):
                    break  # the remaining segments would fail the same way
            except Exception:
                db.rollback()
                log.exception("job segment failed", extra={"job_id": job_id})
                seg = db.get(Segment, seg.id)
                seg.status = "needs_attention"
                db.commit()
                failed += 1
        total_failed = db.execute(select(Segment).where(Segment.job_id == jid, Segment.status.in_(("needs_attention", "not_started")))).scalars().all()
        total_ok = db.execute(select(Segment).where(Segment.job_id == jid, Segment.status.notin_(("needs_attention", "not_started")))).scalars().all()
        job = db.get(TranslationJob, jid)
        job.status = "ready" if not total_failed else ("partial" if total_ok else "failed")
        db.commit()
        audit.record("job.processed", actor=user, object_type="job", object_id=jid, project_id=job.project_id,
                     details={"ok": ok, "failed": failed})
        return job.status


@celery_app.task(name="han.process_job", bind=True, max_retries=2, default_retry_delay=30)
def process_job_task(self, job_id: str) -> str:
    return process_job(job_id)
