"""Stage-2 human evaluation: reviewers score HAN drafts per direction; administrators read the evidence and decide promotion."""
from __future__ import annotations

import hashlib
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit, review_policy
from ..config import get_settings
from ..database import get_db
from ..deps import client_ip, get_current_user, get_user_no_csrf
from ..errors import ApiError, not_found
from ..han import tools
from ..models import schemas as S
from ..models.db import Language, LanguageDirection, LanguageReview, User
from ..ratelimit import enforce
from ..security.permissions import ADMIN_ROLES, require_roles

router = APIRouter(prefix="/v1", tags=["reviews"])

ContentType = Literal["general", "scripture", "ministry", "terminology", "other"]
Severity = Literal["none", "minor", "major", "critical"]

SAMPLE_SENTENCES = [
    ("general", "Good morning, everyone. Please take a seat."),
    ("general", "The meeting will begin at ten o'clock tomorrow."),
    ("general", "Thank you for your patience while we prepare the materials."),
    ("scripture", "For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life."),
    ("scripture", "The Lord is my shepherd; I shall not want."),
    ("scripture", "Love is patient and kind; love does not envy or boast."),
    ("ministry", "We invite you to join us for prayer and worship this Sunday."),
    ("ministry", "Your partnership helps us reach more people with the message of hope."),
    ("ministry", "Please send your testimony to the follow-up team within the week."),
    ("terminology", "Grace, faith, repentance and salvation are central to the Christian message."),
    ("terminology", "The congregation gathered for communion and baptism."),
]


class ReviewDraftIn(S.Req):
    project_id: str
    source_code: Annotated[str, StringConstraints(max_length=16)]
    target_code: Annotated[str, StringConstraints(max_length=16)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class ReviewDraftOut(S.Public):
    version_id: str
    source_text: str
    draft_text: str


class ReviewIn(S.Req):
    source_code: Annotated[str, StringConstraints(max_length=16)]
    target_code: Annotated[str, StringConstraints(max_length=16)]
    source_text: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    draft_text: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    version_id: Optional[str] = None
    content_type: ContentType = "general"
    adequacy: int
    fluency: int
    severity: Severity
    comment: Optional[Annotated[str, StringConstraints(max_length=2000)]] = None


class ReviewOut(S.Public):
    id: str
    source_code: str
    target_code: str
    content_type: str
    adequacy: int
    fluency: int
    severity: str
    comment: Optional[str] = None


def _n(code: str) -> str:
    return code.strip().lower().replace("_", "-")


def _hash(src: str, draft: str) -> str:
    return hashlib.sha256((src.strip() + "\u0000" + draft.strip()).encode()).hexdigest()


@router.get("/reviews/samples")
def samples(user: User = Depends(get_user_no_csrf)):
    return [{"content_type": t, "text": s} for t, s in SAMPLE_SENTENCES]


@router.get("/reviews/policy")
def policy(user: User = Depends(get_user_no_csrf)):
    return {"min_segments_per_reviewer": review_policy.MIN_SEGMENTS_PER_REVIEWER,
            "tiers": {name: vars(th) for name, th in review_policy.THRESHOLDS.items()}}


@router.post("/reviews/draft", response_model=ReviewDraftOut)
def draft(body: ReviewDraftIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce("translate", str(user.id), get_settings().rate_limit_translate_per_min)
    src, tgt = _n(body.source_code), _n(body.target_code)
    result = tools.translate(db, user, body.project_id, src, tgt, body.text)
    return ReviewDraftOut(version_id=result.version_id, source_text=result.source_text, draft_text=result.translated_text)


@router.post("/reviews", response_model=ReviewOut, status_code=201)
def submit(body: ReviewIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == "auditor":
        raise ApiError(403, "forbidden", "Your role cannot submit reviews.")
    src, tgt = _n(body.source_code), _n(body.target_code)
    direction = db.get(LanguageDirection, (src, tgt))
    if direction is None or direction.readiness_tier == "unsupported":
        raise ApiError(422, "direction_unsupported", "This language direction is not open for review yet.")
    if not (1 <= body.adequacy <= 5 and 1 <= body.fluency <= 5):
        raise ApiError(422, "validation_error", "Scores must be between 1 and 5.")
    row = LanguageReview(source_code=src, target_code=tgt, reviewer_id=user.id, version_id=_uuid_or_none(body.version_id),
                         source_text=body.source_text.strip(), draft_text=body.draft_text.strip(),
                         text_hash=_hash(body.source_text, body.draft_text), content_type=body.content_type,
                         adequacy=body.adequacy, fluency=body.fluency, severity=body.severity, comment=body.comment)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "already_reviewed", "You have already scored this draft.")
    audit.record("review.submitted", actor=user, object_type="language_direction", object_id=f"{src}->{tgt}", ip=client_ip(request))
    return _out(row)


@router.get("/reviews/mine", response_model=List[ReviewOut])
def mine(source_code: str = Query(..., max_length=16), target_code: str = Query(..., max_length=16),
         user: User = Depends(get_user_no_csrf), db: Session = Depends(get_db)):
    rows = db.execute(select(LanguageReview).where(LanguageReview.reviewer_id == user.id, LanguageReview.source_code == _n(source_code),
                                                   LanguageReview.target_code == _n(target_code))
                      .order_by(LanguageReview.created_at.desc()).limit(200)).scalars()
    return [_out(r) for r in rows]


def _uuid_or_none(v: Optional[str]):
    import uuid

    try:
        return uuid.UUID(v) if v else None
    except ValueError:
        return None


def _out(r: LanguageReview) -> ReviewOut:
    return ReviewOut(id=str(r.id), source_code=r.source_code, target_code=r.target_code, content_type=r.content_type,
                     adequacy=r.adequacy, fluency=r.fluency, severity=r.severity, comment=r.comment)


# ------------------------------------------------------------------ administrator evidence
def _admin(request: Request, user: User = Depends(get_user_no_csrf)) -> User:
    require_roles(user, *ADMIN_ROLES, ip=client_ip(request))
    return user


def _evidence(db: Session, d: LanguageDirection, reviews: List[LanguageReview]) -> dict:
    summary = review_policy.summarise([{"reviewer_id": r.reviewer_id, "adequacy": r.adequacy, "fluency": r.fluency, "severity": r.severity,
                                        "content_type": r.content_type, "created_at": r.created_at} for r in reviews])
    return {"source_code": d.source_code, "target_code": d.target_code, "tier": d.readiness_tier, "technical_status": d.technical_status,
            "validation_status": d.validation_status, "summary": summary,
            "readiness": review_policy.readiness(summary, d.readiness_tier, d.technical_status)}


@router.get("/admin/language-evidence")
def evidence_list(ready_only: bool = Query(False), actor: User = Depends(_admin), db: Session = Depends(get_db)):
    reviews = db.execute(select(LanguageReview)).scalars().all()
    grouped: dict = {}
    for r in reviews:
        grouped.setdefault((r.source_code, r.target_code), []).append(r)
    out = []
    for (src, tgt), rows in grouped.items():
        d = db.get(LanguageDirection, (src, tgt))
        if d is None:
            continue
        item = _evidence(db, d, rows)
        if ready_only and not item["readiness"]["ready_for"]:
            continue
        item["readiness"].pop("criteria")
        names = {l.code: l.display_name for l in db.execute(select(Language).where(Language.code.in_([src, tgt]))).scalars()}
        item["source_name"], item["target_name"] = names.get(src, src), names.get(tgt, tgt)
        out.append(item)
    out.sort(key=lambda x: (not x["readiness"]["ready_for"], -x["summary"]["segments"]))
    return out


@router.get("/admin/language-evidence/{source_code}/{target_code}")
def evidence_detail(source_code: str, target_code: str, actor: User = Depends(_admin), db: Session = Depends(get_db)):
    src, tgt = _n(source_code), _n(target_code)
    d = db.get(LanguageDirection, (src, tgt))
    if d is None:
        raise not_found("Language direction")
    rows = db.execute(select(LanguageReview, User).join(User, User.id == LanguageReview.reviewer_id)
                      .where(LanguageReview.source_code == src, LanguageReview.target_code == tgt)
                      .order_by(LanguageReview.created_at.desc())).all()
    item = _evidence(db, d, [r for r, _ in rows])
    names = {l.code: l.display_name for l in db.execute(select(Language).where(Language.code.in_([src, tgt]))).scalars()}
    item["source_name"], item["target_name"] = names.get(src, src), names.get(tgt, tgt)
    item["reviews"] = [{"id": str(r.id), "reviewer": u.display_name, "source_text": r.source_text, "draft_text": r.draft_text,
                        "content_type": r.content_type, "adequacy": r.adequacy, "fluency": r.fluency, "severity": r.severity,
                        "comment": r.comment, "created_at": r.created_at.isoformat()} for r, u in rows]
    return item


@router.post("/admin/language-evidence/{source_code}/{target_code}/promote")
def promote(source_code: str, target_code: str, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Apply the promotion the evidence supports. Only an administrator can; the evidence must meet the thresholds."""
    require_roles(actor, *ADMIN_ROLES, ip=client_ip(request))
    src, tgt = _n(source_code), _n(target_code)
    d = db.get(LanguageDirection, (src, tgt))
    if d is None:
        raise not_found("Language direction")
    rows = db.execute(select(LanguageReview).where(LanguageReview.source_code == src, LanguageReview.target_code == tgt)).scalars().all()
    ev = _evidence(db, d, rows)
    target_tier = ev["readiness"]["ready_for"]
    if not target_tier:
        raise ApiError(409, "not_ready", "This direction does not yet meet the evidence thresholds.")
    d.readiness_tier, d.validation_status, d.updated_by = target_tier, "validated", actor.id
    d.review_note = ("Validated by TNI reviewers. Review drafts as usual." if target_tier == "assisted"
                     else "Validated for production use by TNI reviewers.")
    db.commit()
    audit.record("admin.direction_promoted", actor=actor, object_type="language_direction", object_id=f"{src}->{tgt}",
                 details={"tier": target_tier}, ip=client_ip(request))
    return {"source_code": src, "target_code": tgt, "tier": target_tier}
