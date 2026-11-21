"""Rhapsody publication lifecycle and secure source ingestion."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
import zipfile
from calendar import monthrange
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from xml.etree import ElementTree as ET

from docx import Document
from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from .. import rhapsody_draft as drafting
from .. import rhapsody_layout as layout
from .. import rhapsody_plans as plans_mod
from ..config import get_settings
from ..legacy_doc import LegacyDocError, extract_paragraphs, is_legacy_doc
from ..database import get_db
from ..deps import client_ip, get_current_user
from ..errors import ApiError, not_found
from ..models.db import (
    ChatMessage, Language, RhapsodyAssignment, RhapsodyEdition, RhapsodyMasterVersion,
    RhapsodySegment, RhapsodySection, RhapsodySourceFile, RhapsodySegmentTranslation,
    RhapsodyTranslationVersion, RhapsodyComment, RhapsodyReview, User,
)
from ..security.permissions import ADMIN_ROLES, parse_uuid, require_roles

router = APIRouter(prefix="/v1/rhapsody", tags=["rhapsody"])
MAX_UPLOAD = 25 * 1024 * 1024
ALLOWED_EXTENSIONS = {".docx": "docx", ".docm": "docx", ".doc": "docx", ".dot": "docx", ".xlf": "xliff", ".xliff": "xliff"}


def admin_user(request: Request, user: User = Depends(get_current_user)) -> User:
    require_roles(user, *ADMIN_ROLES, ip=client_ip(request))
    return user


class EditionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2200)
    title: Optional[str] = Field(default=None, max_length=200)


class SegmentSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_text: str = Field(min_length=1, max_length=200000)
    expected_version_id: Optional[str] = None


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(pattern="^(approved|changes_requested)$")
    note: Optional[str] = Field(default=None, max_length=3000)


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=3000)
    segment_id: Optional[str] = None


class AssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    master_version_id: str
    target_language: str = Field(min_length=2, max_length=16)
    translator_id: str
    reviewer_id: Optional[str] = None
    due_at: Optional[datetime] = None


def _edition_out(db: Session, e: RhapsodyEdition) -> dict:
    sources = list(db.execute(select(RhapsodySourceFile).where(RhapsodySourceFile.edition_id == e.id).order_by(RhapsodySourceFile.created_at)).scalars())
    versions = list(db.execute(select(RhapsodyMasterVersion).where(RhapsodyMasterVersion.edition_id == e.id).order_by(RhapsodyMasterVersion.version_number.desc())).scalars())
    return {
        "id": str(e.id), "title": e.title, "month": e.month, "year": e.year, "status": e.status,
        "active_master_version_id": str(e.active_master_version_id) if e.active_master_version_id else None,
        "sources": [{"id": str(s.id), "filename": s.filename, "format": s.format, "byte_size": s.byte_size, "sha256": s.sha256, "created_at": s.created_at} for s in sources],
        "master_versions": [{"id": str(v.id), "version_number": v.version_number, "segment_count": len(v.structure.get("segments", [])), "section_count": len(v.structure.get("sections", [])), "validation": v.validation, "activated_at": v.activated_at} for v in versions],
        "created_at": e.created_at, "updated_at": e.updated_at,
    }


def _get_edition(db: Session, edition_id: str) -> RhapsodyEdition:
    row = db.get(RhapsodyEdition, parse_uuid(edition_id, "edition"))
    if row is None:
        raise not_found("edition")
    return row


def _parse_legacy_doc(data: bytes) -> tuple[list[dict], list[dict]]:
    try:
        texts = extract_paragraphs(data)
    except LegacyDocError:
        raise ApiError(422, "invalid_doc", "The Word document could not be read. Save it as .docx and upload it again.")
    sections = [{"stable_key": "front-matter", "section_type": "front_matter", "title": "Front matter", "sequence": 0, "day_number": None}]
    segments = [{"stable_key": f"docx-p-{i+1}", "source_text": t, "source_markup": None, "sequence": i, "section_key": "front-matter", "metadata": {"paragraph_style": "", "runs": []}}
                for i, t in enumerate(texts)]
    return sections, segments


def _parse_docx(data: bytes) -> tuple[list[dict], list[dict]]:
    from io import BytesIO
    if is_legacy_doc(data):
        return _parse_legacy_doc(data)
    try:
        doc = Document(BytesIO(data))
    except Exception:
        raise ApiError(422, "invalid_docx", "The Word document could not be read. Please upload a valid DOCX file.")
    sections: list[dict] = []
    segments: list[dict] = []
    current = {"stable_key": "front-matter", "section_type": "front_matter", "title": "Front matter", "sequence": 0, "day_number": None}
    sections.append(current)
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = paragraph.style.name if paragraph.style else ""
        day = re.search(r"(?i)\bday\s+(\d{1,2})\b", text)
        if day and ("heading" in style.lower() or len(text) < 100):
            n = int(day.group(1))
            current = {"stable_key": f"day-{n}", "section_type": "daily_article", "title": text[:500], "sequence": len(sections), "day_number": n}
            sections.append(current)
        elif ("heading" in style.lower() or text.isupper()) and current["section_type"] == "front_matter":
            current["title"] = text[:500]
        runs = [{"text": run.text, "bold": bool(run.bold), "italic": bool(run.italic), "underline": bool(run.underline), "style": style} for run in paragraph.runs if run.text]
        segments.append({"stable_key": f"docx-p-{len(segments)+1}", "source_text": text, "source_markup": None, "sequence": len(segments), "section_key": current["stable_key"], "metadata": {"paragraph_style": style, "runs": runs}})
    return sections, segments


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_xliff(data: bytes) -> tuple[list[dict], list[dict]]:
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ApiError(422, "unsafe_xml", "The XLIFF file contains unsupported XML declarations.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise ApiError(422, "invalid_xliff", "The XLIFF file is not valid XML.")
    sections = [{"stable_key": "xliff-content", "section_type": "content", "title": "Imported XLIFF content", "sequence": 0, "day_number": None}]
    segments = []
    for node in root.iter():
        name = _local(node.tag)
        if name not in {"trans-unit", "segment"}:
            continue
        source = next((child for child in list(node) if _local(child.tag) == "source"), None)
        if source is None:
            continue
        sid = node.attrib.get("id") or f"xliff-{len(segments)+1}"
        txt = "".join(source.itertext()).strip()
        if not txt:
            continue
        markup = ET.tostring(source, encoding="unicode")
        segments.append({"stable_key": f"xliff-{sid}", "source_text": txt, "source_markup": markup, "sequence": len(segments), "section_key": "xliff-content", "metadata": {"trans_unit_id": sid, "xliff_element": name, "attributes": dict(node.attrib)}})
    if not segments:
        raise ApiError(422, "empty_xliff", "No translatable source segments were found in this XLIFF file.")
    return sections, segments


def _parse_source(fmt: str, data: bytes):
    if fmt == "docx":
        return _parse_docx(data)
    return _parse_xliff(data)


def _source_path(storage_key: str) -> Path:
    base = Path(get_settings().rhapsody_storage_dir).resolve()
    candidate = (base / storage_key).resolve()
    if base not in candidate.parents:
        raise ApiError(500, "storage_error", "The stored source file path is invalid.")
    return candidate


@router.get("/editions")
def list_editions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(RhapsodyEdition).order_by(RhapsodyEdition.year.desc(), RhapsodyEdition.month.desc())
    if user.role not in ADMIN_ROLES:
        stmt = stmt.where(RhapsodyEdition.status == "active")
    return [_edition_out(db, e) for e in db.execute(stmt).scalars()]


@router.post("/editions", status_code=201)
def create_edition(body: EditionCreate, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    title = body.title.strip() if body.title else datetime(body.year, body.month, 1).strftime("%B %Y")
    row = RhapsodyEdition(title=title, month=body.month, year=body.year, created_by=actor.id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "edition_exists", "An edition already exists for that month.")
    db.refresh(row)
    audit.record("rhapsody.edition_created", actor=actor, object_type="rhapsody_edition", object_id=row.id, ip=client_ip(request))
    return _edition_out(db, row)


def _images_dir(edition_id: Any, create: bool = True) -> Path:
    base = Path(get_settings().rhapsody_storage_dir).resolve()
    target = (base / str(edition_id) / "images").resolve()
    if base not in target.parents:
        raise ApiError(500, "storage_error", "The image path is invalid.")
    if create:
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
    return target


def edition_images(edition_id: Any) -> dict[int, bytes]:
    """The banner photo of each daily article, keyed by day number."""
    folder = _images_dir(edition_id, create=False)
    out: dict[int, bytes] = {}
    if folder.is_dir():
        for f in folder.glob("day-*.jpg"):
            try:
                out[int(f.stem.split("-")[1])] = f.read_bytes()
            except (ValueError, OSError):
                continue
    return out


def _plans_path(edition_id: Any) -> Path:
    base = Path(get_settings().rhapsody_storage_dir).resolve()
    return base / str(edition_id) / "plans.json"


def load_plans(edition_id: Any) -> dict[int, tuple[str, str]]:
    try:
        raw = json.loads(_plans_path(edition_id).read_text("utf-8"))
        return {int(k): (v[0], v[1]) for k, v in raw.items()}
    except (OSError, ValueError, IndexError, TypeError):
        return {}


@router.get("/editions/{edition_id}/reading-plans/template")
def reading_plans_template(edition_id: str, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    edition = _get_edition(db, edition_id)
    data = plans_mod.build_template(edition.year, edition.month, load_plans(edition.id))
    name = f"reading-plans-{edition.year}-{edition.month:02d}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/editions/{edition_id}/reading-plans")
def reading_plans_status(edition_id: str, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    edition = _get_edition(db, edition_id)
    saved = load_plans(edition.id)
    return {"days": sorted(saved), "expected": monthrange(edition.year, edition.month)[1]}


@router.post("/editions/{edition_id}/reading-plans", status_code=201)
async def upload_reading_plans(edition_id: str, request: Request, file: UploadFile = File(...),
                               actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Stores the filled-in plan sheet and, when a manuscript has already been laid out, rebuilds the master as a new version that includes it."""
    edition = _get_edition(db, edition_id)
    data = await file.read(2_000_001)
    if not data or len(data) > 2_000_000:
        raise ApiError(413, "plans_size", "The reading-plan file must be under 2 MB.")
    try:
        parsed, warnings = plans_mod.parse_plans(data, file.filename or "", edition.year, edition.month)
    except plans_mod.PlanFileError as exc:
        raise ApiError(422, "invalid_plans", str(exc))
    path = _plans_path(edition.id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps({str(k): list(v) for k, v in parsed.items()}), "utf-8")
    latest = db.execute(select(RhapsodyMasterVersion).where(RhapsodyMasterVersion.edition_id == edition.id)
                        .order_by(RhapsodyMasterVersion.version_number.desc())).scalars().first()
    result = None
    source = db.get(RhapsodySourceFile, latest.source_file_id) if latest and latest.source_file_id else None
    if source is not None and source.format == "docx":
        tpl = (latest.structure or {}).get("template")
        inherit = (tpl["units"], tpl.get("name") or "this edition") if tpl and tpl.get("units") else None
        result = ingest_edition(db, edition, source, None, actor, request, inherit=inherit)
    audit.record("rhapsody.plans_uploaded", actor=actor, object_type="rhapsody_edition", object_id=edition.id, ip=client_ip(request), details={"days": len(parsed)})
    return {"days": sorted(parsed), "warnings": warnings, "master_version_id": (result or {}).get("master_version_id"), "rebuilt": result is not None}


@router.get("/editions/{edition_id}/images")
def list_images(edition_id: str, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    edition = _get_edition(db, edition_id)
    return {"days": sorted(edition_images(edition.id)), "expected": monthrange(edition.year, edition.month)[1]}


@router.post("/editions/{edition_id}/images", status_code=201)
async def upload_image(edition_id: str, file: UploadFile = File(...), day: Optional[int] = Form(None),
                       actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    """The photo printed at the top of a daily article. The day comes from the form or from the first number in the file name."""
    from io import BytesIO
    from PIL import Image, ImageOps

    edition = _get_edition(db, edition_id)
    if day is None:
        m = re.search(r"\d{1,2}", Path(file.filename or "").stem)
        day = int(m.group()) if m else None
    last = monthrange(edition.year, edition.month)[1]
    if day is None or not 1 <= day <= last:
        raise ApiError(422, "image_day", f"Name the file after its day (for example 1.jpg or day-12.png); this month has {last} days.")
    data = await file.read(8_000_001)
    if not data or len(data) > 8_000_000:
        raise ApiError(413, "image_size", "Each image must be under 8 MB.")
    try:
        img = ImageOps.exif_transpose(Image.open(BytesIO(data)))
        img.load()
    except Exception:
        raise ApiError(422, "invalid_image", "Upload a JPG or PNG image.")
    if img.format not in {"JPEG", "PNG"} and Path(file.filename or "").suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ApiError(422, "invalid_image", "Upload a JPG or PNG image.")
    img = img.convert("RGB")
    img.thumbnail((1800, 1800))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=88)
    target = _images_dir(edition.id) / f"day-{day:02d}.jpg"
    target.write_bytes(buf.getvalue())
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return {"day": day}


@router.delete("/editions/{edition_id}", status_code=204)
def delete_edition(edition_id: str, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Removes the edition and everything hanging off it: unsubmitted translations (segments, versions, comments, reviews), master versions,
    sections, segments, source files on disk and chat shortcuts that pointed at them. Submitted or approved work blocks the deletion."""
    row = _get_edition(db, edition_id)
    master_ids = [m for (m,) in db.execute(select(RhapsodyMasterVersion.id).where(RhapsodyMasterVersion.edition_id == row.id))]
    assignments = db.execute(select(RhapsodyAssignment).where(RhapsodyAssignment.master_version_id.in_(master_ids))).scalars().all() if master_ids else []
    if any(a.status in ("submitted", "in_review", "approved", "published") for a in assignments):
        raise ApiError(409, "edition_in_use", "This edition has submitted or approved translations and cannot be deleted.")
    keys = [k for (k,) in db.execute(select(RhapsodySourceFile.storage_key).where(RhapsodySourceFile.edition_id == row.id))]
    title, eid = row.title, row.id
    a_ids = [a.id for a in assignments]
    if a_ids:
        tr_ids = select(RhapsodySegmentTranslation.id).where(RhapsodySegmentTranslation.assignment_id.in_(a_ids))
        db.execute(RhapsodySegmentTranslation.__table__.update().where(RhapsodySegmentTranslation.assignment_id.in_(a_ids)).values(current_version_id=None))
        db.execute(RhapsodyTranslationVersion.__table__.update().where(RhapsodyTranslationVersion.segment_translation_id.in_(tr_ids)).values(parent_version_id=None))
        db.execute(RhapsodyTranslationVersion.__table__.delete().where(RhapsodyTranslationVersion.segment_translation_id.in_(tr_ids)))
        for model in (RhapsodyComment, RhapsodyReview, RhapsodySegmentTranslation):
            db.execute(model.__table__.delete().where(model.assignment_id.in_(a_ids)))
        db.execute(RhapsodyAssignment.__table__.delete().where(RhapsodyAssignment.id.in_(a_ids)))
    if master_ids:
        db.execute(RhapsodyEdition.__table__.update().where(RhapsodyEdition.id == row.id).values(active_master_version_id=None))
        db.execute(RhapsodySection.__table__.update().where(RhapsodySection.master_version_id.in_(master_ids)).values(parent_id=None))
        db.execute(RhapsodySegment.__table__.delete().where(RhapsodySegment.master_version_id.in_(master_ids)))
        db.execute(RhapsodySection.__table__.delete().where(RhapsodySection.master_version_id.in_(master_ids)))
        db.execute(RhapsodyMasterVersion.__table__.delete().where(RhapsodyMasterVersion.id.in_(master_ids)))
    db.execute(RhapsodySourceFile.__table__.delete().where(RhapsodySourceFile.edition_id == eid))
    db.execute(RhapsodyEdition.__table__.delete().where(RhapsodyEdition.id == eid))
    _forget_chat_links(db, [str(eid), *map(str, a_ids)])
    db.commit()
    for key in keys:
        try:
            _source_path(key).unlink(missing_ok=True)
        except (OSError, ApiError):
            pass
    shutil.rmtree(_images_dir(eid, create=False), ignore_errors=True)
    _plans_path(eid).unlink(missing_ok=True)
    audit.record("rhapsody.edition_deleted", actor=actor, object_type="rhapsody_edition", object_id=eid, ip=client_ip(request), details={"title": title})


def _forget_chat_links(db: Session, ids: List[str]) -> None:
    """HAN replies keep 'open' buttons to editions and translations; once those are gone the buttons must go too."""
    for msg in db.execute(select(ChatMessage).where(ChatMessage.role == "assistant")).scalars():
        acts = (msg.meta or {}).get("actions") or []
        keep = [a for a in acts if not any(i in str(a.get("path") or "") for i in ids)]
        if len(keep) != len(acts):
            msg.meta = {**msg.meta, "actions": keep}


@router.get("/editions/{edition_id}")
def get_edition(edition_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _get_edition(db, edition_id)
    if row.status != "active" and user.role not in ADMIN_ROLES:
        raise not_found("edition")
    return _edition_out(db, row)


@router.post("/editions/{edition_id}/sources", status_code=201)
async def upload_source(edition_id: str, request: Request, file: UploadFile = File(...), actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    edition = _get_edition(db, edition_id)
    filename = Path(file.filename or "source").name
    ext = Path(filename).suffix.lower()
    fmt = ALLOWED_EXTENSIONS.get(ext)
    if not fmt:
        raise ApiError(415, "unsupported_format", "Upload a Word document (.doc or .docx), or an XLF/XLIFF file.")
    data = await file.read(MAX_UPLOAD + 1)
    if not data or len(data) > min(MAX_UPLOAD, get_settings().rhapsody_max_upload_bytes):
        raise ApiError(413, "file_size", "The source file is empty or exceeds the 25 MB upload limit.")
    legacy = fmt == "docx" and is_legacy_doc(data)
    if legacy:
        try:
            if not extract_paragraphs(data):
                raise ApiError(422, "empty_doc", "This Word document appears to be empty.")
        except LegacyDocError:
            raise ApiError(422, "invalid_doc", "HAN could not read this Word document. Open it in Word and save it as .docx or .doc (Word 97-2003), then upload it again.")
    elif fmt == "docx" and not data.startswith(b"PK"):
        raise ApiError(422, "invalid_docx", "The uploaded file does not appear to be a valid Word document.")
    if fmt == "xliff" and not data.lstrip().startswith(b"<"):
        raise ApiError(422, "invalid_xliff", "The uploaded file does not appear to be an XML XLIFF file.")
    if fmt == "docx" and not legacy:
        try:
            import io
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if len(zf.namelist()) > 5000 or sum(i.file_size for i in zf.infolist()) > 100_000_000:
                    raise ApiError(413, "docx_expanded_size", "The Word document expands beyond the permitted processing size.")
                if "word/document.xml" not in zf.namelist():
                    raise ApiError(422, "invalid_docx", "The DOCX package is missing its main document.")
        except zipfile.BadZipFile:
            raise ApiError(422, "invalid_docx", "The uploaded Word package is corrupt.")
    settings = get_settings()
    base = Path(settings.rhapsody_storage_dir).resolve()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        base.chmod(0o700)
    except OSError:
        pass
    storage_key = f"{edition.id}/{uuid.uuid4().hex}{ext}"
    target = _source_path(storage_key)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.write_bytes(data)
    try:
        target.chmod(0o600)
        target.parent.chmod(0o700)
    except OSError:
        target.unlink(missing_ok=True)
        raise ApiError(500, "storage_permissions", "The server could not secure the uploaded source file.")
    row = RhapsodySourceFile(edition_id=edition.id, filename=filename[:255], media_type=file.content_type or "application/octet-stream",
        format=fmt, storage_key=storage_key, sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data), uploaded_by=actor.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.record("rhapsody.source_uploaded", actor=actor, object_type="rhapsody_source_file", object_id=row.id,
                 details={"format": fmt, "bytes": len(data)}, ip=client_ip(request))
    return {"id": str(row.id), "filename": row.filename, "format": row.format, "byte_size": row.byte_size, "sha256": row.sha256}


@router.post("/chat-attachment", status_code=201)
async def chat_attachment(request: Request, file: UploadFile = File(...), message: str = Form(""),
                          actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    """The "+" button in HAN chat: file the Word manuscript under the edition named in the message (or the file name)."""
    from ..han.rhapsody_chat import _period

    month, year = _period(message)
    if not month:
        month, year = _period(Path(file.filename or "").stem.replace("_", " "))
    if not month:
        raise ApiError(422, "month_required", "Tell me which month this manuscript is for, for example \"November 2026\", and attach it again.")
    year = year or datetime.now().year
    edition = db.execute(select(RhapsodyEdition).where(RhapsodyEdition.year == year, RhapsodyEdition.month == month)).scalar_one_or_none()
    if edition is None:
        edition = RhapsodyEdition(title=datetime(year, month, 1).strftime("%B %Y"), month=month, year=year, created_by=actor.id)
        db.add(edition)
        db.commit()
        db.refresh(edition)
    out = await upload_source(str(edition.id), request, file, actor, db)
    return {**out, "edition_id": str(edition.id), "edition_title": edition.title}


def _read_source(source: RhapsodySourceFile) -> bytes:
    data = _source_path(source.storage_key).read_bytes()
    if hashlib.sha256(data).hexdigest() != source.sha256:
        raise ApiError(409, "source_checksum_mismatch", "The stored source file failed its integrity check.")
    return data


def _inherited_template(db: Session, exclude_edition: uuid.UUID) -> Optional[tuple[list, str]]:
    """The layout template of the most recent master that has one: cover, introduction and back matter rarely change."""
    for v in db.execute(select(RhapsodyMasterVersion).order_by(RhapsodyMasterVersion.created_at.desc()).limit(12)).scalars():
        tpl = (v.structure or {}).get("template")
        if tpl and tpl.get("units"):
            return tpl["units"], tpl.get("name") or "an earlier edition"
    return None


def ingest_edition(db: Session, edition: RhapsodyEdition, source: RhapsodySourceFile, template_source: Optional[RhapsodySourceFile],
                   actor: User, request: Optional[Request] = None, inherit: Optional[tuple] = None) -> dict:
    """Build a new master version: the month's articles (DOCX) merged into the InDesign layout template (XLIFF)."""
    data = _read_source(source)
    template_units: Optional[list] = None
    template_name: Optional[str] = None
    info: dict = {}
    if source.format == "docx":
        if template_source is not None and template_source.format != "xliff":
            raise ApiError(422, "invalid_template", "The layout template must be an XLIFF file exported from InDesign.")
        if template_source is not None:
            try:
                template_units, template_name = layout.parse_template(_read_source(template_source)), template_source.filename
            except (ET.ParseError, ValueError):
                raise ApiError(422, "invalid_xliff", "The layout template is not valid XLIFF.")
        else:
            inherited = inherit or _inherited_template(db, edition.id)
            if inherited:
                template_units, template_name = inherited[0], inherited[1]
        try:
            articles = layout.parse_manuscript(data, edition.year, edition.month)
        except ApiError:
            raise
        except Exception:
            raise ApiError(422, "invalid_docx", "The Word document could not be read. Please upload a valid DOCX file.")
        saved_plans = load_plans(edition.id)
        for art in articles:
            if art["day"] in saved_plans:
                art["plan1"], art["plan2"] = saved_plans[art["day"]]
        if articles:
            sections, segments, info = layout.build_master(edition.year, edition.month, articles, template_units)
            validation = layout.validate_master(edition.year, edition.month, articles, template_units is not None)
            if template_units is not None and template_source is None:
                validation["warnings"].append(f"The layout template of {template_name} was reused for the cover, introduction and back matter.")
        else:
            sections, segments = _parse_docx(data)
            validation = layout.validate_master(edition.year, edition.month, [], template_units is not None)
            validation["blocking_errors"] = []
            validation["warnings"].insert(0, "No dated article headings were recognised, so the manuscript was split into plain paragraphs. Review it carefully before activating.")
            detected = [i.get("day_number") for i in sections if i.get("day_number") is not None]
            if detected:
                validation["articles"] = len(detected)
    else:
        sections, segments = _parse_xliff(data)
        validation = {"articles": 0, "expected_articles": monthrange(edition.year, edition.month)[1], "missing_days": [], "warnings": [
            "This master comes from an XLIFF layout only. Upload the Word manuscript with this layout as its template to place the month's articles."], "blocking_errors": []}
    if not segments:
        raise ApiError(422, "empty_source", "No non-empty paragraphs or translatable segments were found.")
    validation.update({"segment_count": len(segments), "section_count": len(sections), "locked_segments": info.get("locked", 0)})
    latest = db.execute(select(RhapsodyMasterVersion).where(RhapsodyMasterVersion.edition_id == edition.id).order_by(RhapsodyMasterVersion.version_number.desc())).scalars().first()
    version_number = (latest.version_number + 1) if latest else 1
    structure: dict = {"sections": sections, "segments": segments, "source_format": source.format}
    if template_units is not None:
        structure["template"] = {"name": template_name, "units": template_units}
    version = RhapsodyMasterVersion(edition_id=edition.id, version_number=version_number, source_file_id=source.id, structure=structure,
                                    validation=validation, created_by=actor.id)
    db.add(version)
    db.flush()
    section_ids = {}
    for item in sections:
        section = RhapsodySection(master_version_id=version.id, stable_key=item["stable_key"], section_type=item["section_type"],
                                  title=item.get("title"), sequence=item["sequence"], day_number=item.get("day_number"), formatting=item.get("formatting") or {})
        db.add(section)
        db.flush()
        section_ids[item["stable_key"]] = section.id
    for item in segments:
        db.add(RhapsodySegment(master_version_id=version.id, section_id=section_ids[item["section_key"]], stable_key=item["stable_key"],
                               source_text=item["source_text"], source_markup=item.get("source_markup"), sequence=item["sequence"], metadata_json=item.get("metadata", {})))
    if edition.active_master_version_id is None:
        edition.status = "ready"
    db.commit()
    db.refresh(version)
    audit.record("rhapsody.master_ingested", actor=actor, object_type="rhapsody_master_version", object_id=version.id,
                 details={"version": version_number, "segments": len(segments), "sections": len(sections), "format": source.format,
                          "articles": validation.get("articles")}, ip=client_ip(request) if request else None)
    return {"edition_id": str(edition.id), "master_version_id": str(version.id), "version_number": version_number, "validation": validation}


@router.post("/editions/{edition_id}/ingest")
def ingest_source(edition_id: str, request: Request, source_file_id: str = Form(...), template_file_id: Optional[str] = Form(None),
                  actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    edition = _get_edition(db, edition_id)
    source = db.get(RhapsodySourceFile, parse_uuid(source_file_id, "source file"))
    if source is None or source.edition_id != edition.id:
        raise not_found("source file")
    template = None
    if template_file_id:
        template = db.get(RhapsodySourceFile, parse_uuid(template_file_id, "template file"))
        if template is None or template.edition_id != edition.id:
            raise not_found("template file")
    return ingest_edition(db, edition, source, template, actor, request)


@router.get("/editions/{edition_id}/masters/{master_version_id}")
def get_master_preview(edition_id: str, master_version_id: str, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    edition = _get_edition(db, edition_id)
    version = db.get(RhapsodyMasterVersion, parse_uuid(master_version_id, "master version"))
    if version is None or version.edition_id != edition.id:
        raise not_found("master version")
    sections = list(db.execute(select(RhapsodySection).where(RhapsodySection.master_version_id == version.id).order_by(RhapsodySection.sequence)).scalars())
    segments = list(db.execute(select(RhapsodySegment).where(RhapsodySegment.master_version_id == version.id).order_by(RhapsodySegment.sequence)).scalars())
    return {
        "id": str(version.id), "version_number": version.version_number, "validation": version.validation,
        "sections": [{"id": str(s.id), "stable_key": s.stable_key, "type": s.section_type, "title": s.title, "sequence": s.sequence, "day_number": s.day_number, "formatting": s.formatting} for s in sections],
        "segments": [{"id": str(s.id), "stable_key": s.stable_key, "section_id": str(s.section_id), "source_text": s.source_text, "source_markup": s.source_markup, "sequence": s.sequence, "metadata": s.metadata_json} for s in segments],
    }


@router.post("/editions/{edition_id}/activate")
def activate_master(edition_id: str, master_version_id: str, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    edition = _get_edition(db, edition_id)
    version = db.get(RhapsodyMasterVersion, parse_uuid(master_version_id, "master version"))
    if version is None or version.edition_id != edition.id:
        raise not_found("master version")
    if version.validation.get("blocking_errors"):
        raise ApiError(409, "master_validation_failed", "Resolve blocking master validation issues before activation.")
    if not db.execute(select(RhapsodySegment.id).where(RhapsodySegment.master_version_id == version.id).limit(1)).first():
        raise ApiError(409, "empty_master", "A master must contain translatable content before activation.")
    now = datetime.now(timezone.utc)
    version.activated_at = now
    edition.active_master_version_id = version.id
    edition.status = "active"
    db.commit()
    audit.record("rhapsody.master_activated", actor=actor, object_type="rhapsody_master_version", object_id=version.id,
                 details={"edition_id": str(edition.id), "version": version.version_number}, ip=client_ip(request))
    return {"edition_id": str(edition.id), "active_master_version_id": str(version.id), "status": edition.status}


def _assignment_out(row: RhapsodyAssignment) -> dict:
    return {"id": str(row.id), "master_version_id": str(row.master_version_id), "target_language": row.target_language,
            "translator_id": str(row.translator_id), "reviewer_id": str(row.reviewer_id) if row.reviewer_id else None,
            "due_at": row.due_at, "status": row.status, "draft_status": row.draft_status}


def make_assignment(db: Session, actor: User, master: RhapsodyMasterVersion, lang: str, translator: User, reviewer_id: Optional[uuid.UUID] = None,
                    due_at: Optional[datetime] = None, request: Optional[Request] = None) -> RhapsodyAssignment:
    edition = db.get(RhapsodyEdition, master.edition_id)
    if edition is None or edition.status != "active" or edition.active_master_version_id != master.id:
        raise ApiError(409, "master_not_active", "Assignments can only use the currently active English master.")
    if db.get(Language, lang) is None:
        raise ApiError(422, "unknown_language", "The target language is not registered in HAN.")
    if lang == "en":
        raise ApiError(422, "same_language", "The Rhapsody master is English; choose a target language other than English.")
    row = RhapsodyAssignment(master_version_id=master.id, target_language=lang, translator_id=translator.id, reviewer_id=reviewer_id,
                             due_at=due_at, created_by=actor.id)
    db.add(row)
    db.flush()
    for segment in db.execute(select(RhapsodySegment).where(RhapsodySegment.master_version_id == master.id)).scalars():
        db.add(RhapsodySegmentTranslation(assignment_id=row.id, segment_id=segment.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "assignment_exists", "That translator already has an assignment for this language and master.")
    db.refresh(row)
    drafting.prefill_locked(db, row, translator)
    audit.record("rhapsody.assignment_created", actor=actor, object_type="rhapsody_assignment", object_id=row.id,
                 details={"language": lang, "master_version": str(master.id)}, ip=client_ip(request) if request else None)
    return row


def start_for_translator(db: Session, user: User, edition: RhapsodyEdition, language: str, request: Optional[Request] = None) -> tuple[RhapsodyAssignment, bool]:
    """A translator opens (or resumes) their own translation of an activated edition. Returns (assignment, created)."""
    if user.role not in {"translator", *ADMIN_ROLES}:
        raise ApiError(403, "forbidden", "Only translators can start a Rhapsody translation.")
    if edition.status != "active" or edition.active_master_version_id is None:
        raise ApiError(409, "master_not_active", f"The {edition.title} master has not been activated yet.")
    lang = language.strip().lower().replace("_", "-")
    if user.role == "translator":
        # Rhapsody is always English -> the translator's own language; a client can't choose another one
        if not user.expertise_language:
            raise ApiError(422, "no_expertise_language", "Choose your language of expertise in your profile before starting a Rhapsody translation.")
        lang = user.expertise_language
    master = db.get(RhapsodyMasterVersion, edition.active_master_version_id)
    existing = db.execute(select(RhapsodyAssignment).where(RhapsodyAssignment.master_version_id == master.id,
                                                           RhapsodyAssignment.target_language == lang,
                                                           RhapsodyAssignment.translator_id == user.id)).scalar_one_or_none()
    if existing is not None:
        return existing, False
    return make_assignment(db, user, master, lang, user, request=request), True


@router.post("/assignments", status_code=201)
def create_assignment(body: AssignmentCreate, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    master = db.get(RhapsodyMasterVersion, parse_uuid(body.master_version_id, "master version"))
    if master is None:
        raise not_found("master version")
    lang = body.target_language.strip().lower().replace("_", "-")
    translator = db.get(User, parse_uuid(body.translator_id, "translator"))
    if translator is None or translator.status != "active" or translator.role != "translator":
        raise ApiError(422, "invalid_translator", "Choose an active HAN translator.")
    reviewer_id = parse_uuid(body.reviewer_id, "reviewer") if body.reviewer_id else None
    if reviewer_id:
        reviewer = db.get(User, reviewer_id)
        if reviewer is None or reviewer.status != "active" or reviewer.role not in {"reviewer", "tni_admin", "technical_admin"}:
            raise ApiError(422, "invalid_reviewer", "Choose an active reviewer or administrator.")
    row = make_assignment(db, actor, master, lang, translator, reviewer_id, body.due_at, request)
    return _assignment_out(row)


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str = Field(min_length=2, max_length=16)
    draft: bool = True


@router.post("/editions/{edition_id}/start", status_code=201)
def start_translation(edition_id: str, body: StartIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    edition = _get_edition(db, edition_id)
    if edition.status != "active" and user.role not in ADMIN_ROLES:
        raise not_found("edition")
    row, created = start_for_translator(db, user, edition, body.language, request)
    drafted = False
    if body.draft and row.draft_status in {"idle", "failed"}:
        drafted = drafting.start_drafting(db, row, user)
        db.refresh(row)
    return {**_assignment_out(row), "created": created, "drafting": drafted}


@router.get("/assignments")
def list_assignments(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(RhapsodyAssignment).order_by(RhapsodyAssignment.created_at.desc())
    if user.role not in ADMIN_ROLES:
        if user.role == "reviewer":
            stmt = stmt.where(RhapsodyAssignment.reviewer_id == user.id)
        else:
            stmt = stmt.where(RhapsodyAssignment.translator_id == user.id)
    output = []
    for a in db.execute(stmt).scalars():
        master = db.get(RhapsodyMasterVersion, a.master_version_id)
        edition = db.get(RhapsodyEdition, master.edition_id) if master else None
        output.append({"id": str(a.id), "master_version_id": str(a.master_version_id), "target_language": a.target_language,
            "translator_id": str(a.translator_id), "reviewer_id": str(a.reviewer_id) if a.reviewer_id else None,
            "due_at": a.due_at, "status": a.status, "edition_title": edition.title if edition else "Rhapsody edition",
            "draft_status": a.draft_status, "draft_total": a.draft_total, "draft_done": a.draft_done})
    return output



def _load_assignment(db: Session, assignment_id: str) -> RhapsodyAssignment:
    row = db.get(RhapsodyAssignment, parse_uuid(assignment_id, "assignment"))
    if row is None:
        raise not_found("assignment")
    return row


def _can_access_assignment(row: RhapsodyAssignment, user: User) -> bool:
    return user.role in ADMIN_ROLES or row.translator_id == user.id or (user.role == "reviewer" and row.reviewer_id == user.id)


@router.get("/assignments/{assignment_id}")
def get_assignment(assignment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assignment = _load_assignment(db, assignment_id)
    if not _can_access_assignment(assignment, user):
        raise not_found("assignment")
    master = db.get(RhapsodyMasterVersion, assignment.master_version_id)
    edition = db.get(RhapsodyEdition, master.edition_id)
    segments = list(db.execute(select(RhapsodySegment).where(RhapsodySegment.master_version_id == master.id).order_by(RhapsodySegment.sequence)).scalars())
    section_rows = list(db.execute(select(RhapsodySection).where(RhapsodySection.master_version_id == master.id).order_by(RhapsodySection.sequence)).scalars())
    section_map = {str(s.id): s for s in section_rows}
    translations = {t.segment_id: t for t in db.execute(select(RhapsodySegmentTranslation).where(RhapsodySegmentTranslation.assignment_id == assignment.id)).scalars()}
    version_ids = [t.current_version_id for t in translations.values() if t.current_version_id]
    versions = {v.id: v for v in db.execute(select(RhapsodyTranslationVersion).where(RhapsodyTranslationVersion.id.in_(version_ids))).scalars()} if version_ids else {}
    comments = [{"id": str(c.id), "segment_id": str(c.segment_id) if c.segment_id else None, "author": (db.get(User, c.author_id).display_name if db.get(User, c.author_id) else ""),
                 "body": c.body, "resolved": c.resolved_at is not None, "created_at": c.created_at}
                for c in db.execute(select(RhapsodyComment).where(RhapsodyComment.assignment_id == assignment.id).order_by(RhapsodyComment.created_at)).scalars()]
    result_segments = []
    for seg in segments:
        tr = translations.get(seg.id)
        version = versions.get(tr.current_version_id) if tr and tr.current_version_id else None
        warnings = list((version.meta or {}).get("warnings") or []) if version else []
        if version and not layout.tags_preserved(seg.source_text, version.target_text):
            warnings.append("The layout tags of the English paragraph are missing or changed in this translation.")
        result_segments.append({
            "id": str(seg.id), "stable_key": seg.stable_key, "section_id": str(seg.section_id),
            "source_text": seg.source_text, "source_markup": seg.source_markup, "sequence": seg.sequence,
            "metadata": seg.metadata_json, "translation_status": tr.status if tr else "not_started",
            "translation_id": str(tr.id) if tr else None,
            "current_version_id": str(version.id) if version else None,
            "version_number": version.version_number if version else None,
            "target_text": version.target_text if version else "",
            "origin": version.origin if version else None, "draft_source": (version.meta or {}).get("source") if version else None,
            "glossary": (version.meta or {}).get("glossary", []) if version else [], "warnings": warnings,
        })
    return {
        "id": str(assignment.id), "edition": {"id": str(edition.id), "title": edition.title, "month": edition.month, "year": edition.year},
        "master_version_id": str(master.id), "target_language": assignment.target_language, "status": assignment.status,
        "due_at": assignment.due_at, "can_edit": assignment.status in {"assigned", "in_progress", "changes_requested"} and (assignment.translator_id == user.id or user.role in ADMIN_ROLES),
        "translator": (db.get(User, assignment.translator_id).display_name if db.get(User, assignment.translator_id) else None),
        "draft": {"status": assignment.draft_status, "total": assignment.draft_total, "done": assignment.draft_done, "note": assignment.draft_note},
        "sections": [{"id": str(s.id), "stable_key": s.stable_key, "type": s.section_type, "title": s.title, "sequence": s.sequence, "day_number": s.day_number, "formatting": s.formatting} for s in section_rows],
        "segments": result_segments, "comments": comments,
    }


@router.put("/assignments/{assignment_id}/segments/{segment_id}")
def save_segment(assignment_id: str, segment_id: str, body: SegmentSave, request: Request,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assignment = _load_assignment(db, assignment_id)
    if assignment.translator_id != user.id and user.role not in ADMIN_ROLES:
        raise not_found("assignment")
    if assignment.status not in {"assigned", "in_progress", "changes_requested"}:
        raise ApiError(409, "assignment_locked", "This assignment is no longer editable.")
    segment = db.get(RhapsodySegment, parse_uuid(segment_id, "segment"))
    if segment is None or segment.master_version_id != assignment.master_version_id:
        raise not_found("segment")
    tr = db.execute(select(RhapsodySegmentTranslation).where(
        RhapsodySegmentTranslation.assignment_id == assignment.id,
        RhapsodySegmentTranslation.segment_id == segment.id).with_for_update()).scalar_one_or_none()
    if tr is None:
        raise not_found("segment")
    current = db.get(RhapsodyTranslationVersion, tr.current_version_id) if tr.current_version_id else None
    if current is not None and body.expected_version_id is None:
        raise ApiError(409, "version_conflict", "Reload the latest paragraph version before saving your changes.")
    if body.expected_version_id is not None and (current is None or str(current.id) != body.expected_version_id):
        raise ApiError(409, "version_conflict", "This paragraph has changed since you opened it. Reload the latest version before saving.")
    number = (current.version_number + 1) if current else 1
    version = RhapsodyTranslationVersion(segment_translation_id=tr.id, version_number=number, target_text=body.target_text,
        origin="human", created_by=user.id, parent_version_id=current.id if current else None)
    db.add(version)
    db.flush()
    tr.current_version_id = version.id
    tr.status = "draft"
    assignment.status = "in_progress"
    db.commit()
    db.refresh(version)
    audit.record("rhapsody.segment_saved", actor=user, object_type="rhapsody_translation_version", object_id=version.id,
                 details={"assignment_id": str(assignment.id), "segment_id": str(segment.id), "version": number}, ip=client_ip(request))
    warnings = [] if layout.tags_preserved(segment.source_text, body.target_text) else ["The layout tags of the English paragraph are missing or changed in this translation."]
    return {"segment_id": str(segment.id), "version_id": str(version.id), "version_number": number, "target_text": version.target_text, "status": tr.status,
            "origin": version.origin, "warnings": warnings}


@router.post("/assignments/{assignment_id}/submit")
def submit_assignment(assignment_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assignment = _load_assignment(db, assignment_id)
    if assignment.translator_id != user.id:
        raise not_found("assignment")
    if assignment.status not in {"assigned", "in_progress", "changes_requested"}:
        raise ApiError(409, "assignment_state", "This assignment cannot be submitted in its current state.")
    rows = list(db.execute(select(RhapsodySegmentTranslation).where(RhapsodySegmentTranslation.assignment_id == assignment.id)).scalars())
    if not rows or any(not row.current_version_id for row in rows):
        raise ApiError(409, "incomplete_assignment", "Translate every required paragraph before submitting this edition.")
    unreviewed = db.execute(select(func.count()).select_from(RhapsodyTranslationVersion).where(
        RhapsodyTranslationVersion.id.in_([r.current_version_id for r in rows]), RhapsodyTranslationVersion.origin == "ai")).scalar_one()
    if unreviewed:
        raise ApiError(409, "unreviewed_drafts", f"{unreviewed} paragraph(s) still hold an unreviewed HAN draft. Confirm or correct each one before submitting.")
    for row in rows:
        row.status = "in_review"
    assignment.status = "submitted"
    db.commit()
    audit.record("rhapsody.assignment_submitted", actor=user, object_type="rhapsody_assignment", object_id=assignment.id,
                 details={"segment_count": len(rows)}, ip=client_ip(request))
    return {"assignment_id": str(assignment.id), "status": assignment.status, "submitted_segments": len(rows)}


@router.post("/assignments/{assignment_id}/comments", status_code=201)
def add_comment(assignment_id: str, body: CommentIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assignment = _load_assignment(db, assignment_id)
    if not _can_access_assignment(assignment, user):
        raise not_found("assignment")
    segment_id = parse_uuid(body.segment_id, "segment") if body.segment_id else None
    if segment_id:
        segment = db.get(RhapsodySegment, segment_id)
        if segment is None or segment.master_version_id != assignment.master_version_id:
            raise not_found("segment")
    row = RhapsodyComment(assignment_id=assignment.id, segment_id=segment_id, author_id=user.id, body=body.body)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.record("rhapsody.comment_added", actor=user, object_type="rhapsody_comment", object_id=row.id,
                 details={"assignment_id": str(assignment.id), "segment_id": str(segment_id) if segment_id else None}, ip=client_ip(request))
    return {"id": str(row.id), "body": row.body, "segment_id": str(segment_id) if segment_id else None, "created_at": row.created_at}


@router.post("/assignments/{assignment_id}/review")
def review_assignment(assignment_id: str, body: ReviewIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assignment = _load_assignment(db, assignment_id)
    if user.role not in ADMIN_ROLES and not (user.role == "reviewer" and assignment.reviewer_id == user.id):
        raise not_found("assignment")
    if assignment.status != "submitted":
        raise ApiError(409, "not_submitted", "Only submitted assignments can be reviewed.")
    rows = list(db.execute(select(RhapsodySegmentTranslation).where(RhapsodySegmentTranslation.assignment_id == assignment.id)).scalars())
    if body.decision == "approved" and (not rows or any(not row.current_version_id for row in rows)):
        raise ApiError(409, "incomplete_assignment", "An incomplete translation cannot be approved.")
    review = RhapsodyReview(assignment_id=assignment.id, reviewer_id=user.id, decision=body.decision, note=body.note)
    db.add(review)
    assignment.status = "approved" if body.decision == "approved" else "changes_requested"
    for row in rows:
        row.status = "approved" if body.decision == "approved" else "changes_requested"
    db.commit()
    audit.record("rhapsody.assignment_reviewed", actor=user, object_type="rhapsody_assignment", object_id=assignment.id,
                 details={"decision": body.decision}, ip=client_ip(request))
    return {"assignment_id": str(assignment.id), "status": assignment.status, "decision": body.decision}


@router.post("/assignments/{assignment_id}/draft")
def draft_assignment(assignment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ask HAN to draft every paragraph that has no translation yet (also used to resume after an interruption)."""
    assignment = _load_assignment(db, assignment_id)
    if assignment.translator_id != user.id and user.role not in ADMIN_ROLES:
        raise not_found("assignment")
    if assignment.status not in {"assigned", "in_progress", "changes_requested"}:
        raise ApiError(409, "assignment_locked", "This assignment is no longer editable.")
    translator = db.get(User, assignment.translator_id)
    started = drafting.start_drafting(db, assignment, translator)
    db.refresh(assignment)
    return {"started": started, "draft": {"status": assignment.draft_status, "total": assignment.draft_total, "done": assignment.draft_done, "note": assignment.draft_note}}


@router.get("/assignments/{assignment_id}/progress")
def draft_progress(assignment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assignment = _load_assignment(db, assignment_id)
    if not _can_access_assignment(assignment, user):
        raise not_found("assignment")
    rows = list(db.execute(select(RhapsodySegmentTranslation.current_version_id).where(RhapsodySegmentTranslation.assignment_id == assignment.id)).scalars())
    origins = dict(db.execute(select(RhapsodyTranslationVersion.id, RhapsodyTranslationVersion.origin).where(RhapsodyTranslationVersion.id.in_([r for r in rows if r]))).all()) if any(rows) else {}
    return {"status": assignment.status, "draft": {"status": assignment.draft_status, "total": assignment.draft_total, "done": assignment.draft_done, "note": assignment.draft_note},
            "segments": len(rows), "with_text": sum(1 for r in rows if r), "unreviewed_drafts": sum(1 for r in rows if r and origins.get(r) == "ai")}


@router.post("/assignments/{assignment_id}/segments/{segment_id}/redraft")
def redraft_segment(assignment_id: str, segment_id: str, body: SegmentSave, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A fresh HAN suggestion for one paragraph. The current text stays in the version history. `target_text` is ignored."""
    assignment = _load_assignment(db, assignment_id)
    if assignment.translator_id != user.id and user.role not in ADMIN_ROLES:
        raise not_found("assignment")
    if assignment.status not in {"assigned", "in_progress", "changes_requested"}:
        raise ApiError(409, "assignment_locked", "This assignment is no longer editable.")
    segment = db.get(RhapsodySegment, parse_uuid(segment_id, "segment"))
    if segment is None or segment.master_version_id != assignment.master_version_id:
        raise not_found("segment")
    tr = db.execute(select(RhapsodySegmentTranslation).where(RhapsodySegmentTranslation.assignment_id == assignment.id,
                                                             RhapsodySegmentTranslation.segment_id == segment.id).with_for_update()).scalar_one_or_none()
    if tr is None:
        raise not_found("segment")
    if tr.current_version_id and str(tr.current_version_id) != body.expected_version_id:
        raise ApiError(409, "version_conflict", "This paragraph has changed since you opened it. Reload the latest version before asking for a new draft.")
    project = drafting.rhapsody_project(db)
    from .. import services as svc
    svc.ensure_direction_allowed(db, project, "en", assignment.target_language)
    version = drafting.draft_one(db, db.get(User, assignment.translator_id), assignment, tr, segment, project)
    audit.record("rhapsody.segment_redrafted", actor=user, object_type="rhapsody_translation_version", object_id=version.id,
                 details={"assignment_id": str(assignment.id), "segment_id": str(segment.id)}, ip=client_ip(request))
    return {"segment_id": str(segment.id), "version_id": str(version.id), "version_number": version.version_number, "target_text": version.target_text,
            "origin": version.origin, "draft_source": (version.meta or {}).get("source"), "warnings": (version.meta or {}).get("warnings", []),
            "glossary": (version.meta or {}).get("glossary", [])}


@router.get("/assignments/{assignment_id}/export.docx")
def export_docx(assignment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The translated edition as a Word file in layout order, for proofreading and for the InDesign hand-over."""
    from io import BytesIO
    from docx import Document
    from fastapi.responses import Response

    assignment = _load_assignment(db, assignment_id)
    if not _can_access_assignment(assignment, user):
        raise not_found("assignment")
    master = db.get(RhapsodyMasterVersion, assignment.master_version_id)
    edition = db.get(RhapsodyEdition, master.edition_id)
    sections = list(db.execute(select(RhapsodySection).where(RhapsodySection.master_version_id == master.id).order_by(RhapsodySection.sequence)).scalars())
    segments = list(db.execute(select(RhapsodySegment).where(RhapsodySegment.master_version_id == master.id).order_by(RhapsodySegment.sequence)).scalars())
    texts = {}
    for tr in db.execute(select(RhapsodySegmentTranslation).where(RhapsodySegmentTranslation.assignment_id == assignment.id)).scalars():
        if tr.current_version_id:
            texts[tr.segment_id] = db.get(RhapsodyTranslationVersion, tr.current_version_id).target_text
    doc = Document()
    doc.add_heading(f"Rhapsody of Realities, {edition.title} ({assignment.target_language})", level=0)
    for sec in sections:
        if sec.section_type == "labels":
            continue
        doc.add_heading(sec.title or sec.stable_key, level=1)
        for seg in (x for x in segments if x.section_id == sec.id):
            doc.add_paragraph(texts.get(seg.id) or f"[not translated] {seg.source_text}")
    buf = BytesIO()
    doc.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="rhapsody-{edition.year}-{edition.month:02d}-{assignment.target_language}.docx"'})


# ------------------------------------------------------------------------------------------------- typeset PDF previews
def _typeset_master(db: Session, master: RhapsodyMasterVersion, edition: RhapsodyEdition, texts: Optional[dict] = None,
                    language: str = "en") -> bytes:
    """Lays the master out as the printed book. `texts` maps segment id to translated text; missing entries fall back to the source."""
    from ..models.db import RhapsodyFontAsset, RhapsodyLanguageProfile, RhapsodyProfileFont
    from ..rhapsody_typeset import typeset_pdf
    from .rhapsody_publishing import font_faces, permanent_content

    sections = list(db.execute(select(RhapsodySection).where(RhapsodySection.master_version_id == master.id).order_by(RhapsodySection.sequence)).scalars())
    segments = list(db.execute(select(RhapsodySegment).where(RhapsodySegment.master_version_id == master.id).order_by(RhapsodySegment.sequence)).scalars())
    texts = texts or {}
    kwargs: dict = {}
    profile = db.execute(select(RhapsodyLanguageProfile).where(RhapsodyLanguageProfile.language_code == language)).scalar_one_or_none() if language != "en" else None
    if profile is not None:
        rows = db.execute(select(RhapsodyProfileFont, RhapsodyFontAsset).join(RhapsodyFontAsset, RhapsodyFontAsset.id == RhapsodyProfileFont.font_id)
                          .where(RhapsodyProfileFont.profile_id == profile.id)).all()
        fonts = {a.role: {"family": f.family, "format": f.format, "storage_key": f.storage_key, "sha256": f.sha256, "coverage": f.coverage or {}} for a, f in rows}
        try:
            kwargs["font_css"], kwargs["role_fonts"] = font_faces(fonts)
        except ApiError:
            pass
        cfg = profile.layout or {}
        try:
            kwargs["page_mm"] = (float(cfg.get("page_width_mm", 140)), float(cfg.get("page_height_mm", 220)))
            kwargs["margin_mm"] = float(cfg.get("margin_mm", 12))
            typo = profile.typography or {}
            kwargs["body_pt"] = float(typo.get("body_size_pt", 9.6))
            kwargs["title_pt"] = float(typo.get("heading_size_pt", 13))
            kwargs["scripture_pt"] = float(typo.get("scripture_size_pt", 9))
            kwargs["localization"] = {k: v for k, v in (profile.localization or {}).items() if k != "book_names"}
            kwargs["book_names"] = (profile.localization or {}).get("book_names") or {}
            kwargs["permanent"] = permanent_content(db, language, approved_only=False)
        except (TypeError, ValueError):
            kwargs.pop("page_mm", None)
        kwargs["direction"], kwargs["lang"] = profile.direction, profile.locale
    sec_rows = [{"id": str(s.id), "key": s.stable_key, "type": s.section_type, "day": s.day_number, "formatting": s.formatting or {}} for s in sections]
    blocks = [{"section_id": str(g.section_id), "key": g.stable_key, "role": (g.metadata_json or {}).get("role", "body"),
               "text": texts.get(g.id) or g.source_text, "meta": g.metadata_json or {}} for g in segments]
    kwargs["images"] = edition_images(edition.id)
    return typeset_pdf(sec_rows, blocks, title=f"Rhapsody of Realities {edition.title}", year=edition.year, month=edition.month,
                       month_label=f"{layout.MONTHS[edition.month - 1]} {edition.year}", **kwargs)


def _pdf_response(pdf: bytes, name: str):
    from fastapi.responses import Response
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.get("/editions/{edition_id}/masters/{master_version_id}/layout.pdf")
def master_layout_pdf(edition_id: str, master_version_id: str, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    """The English master typeset like the printed book, so admins review the real layout before activating."""
    edition = _get_edition(db, edition_id)
    master = db.get(RhapsodyMasterVersion, parse_uuid(master_version_id, "master version"))
    if master is None or master.edition_id != edition.id:
        raise not_found("master version")
    try:
        pdf = _typeset_master(db, master, edition)
    except Exception:
        raise ApiError(422, "pdf_render_failed", "HAN could not typeset the layout. Check the server rendering dependencies.")
    return _pdf_response(pdf, f"rhapsody-{edition.year}-{edition.month:02d}-english.pdf")


@router.get("/assignments/{assignment_id}/layout.pdf")
def assignment_layout_pdf(assignment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The translation so far typeset in the book layout; untranslated paragraphs show the English."""
    assignment = _load_assignment(db, assignment_id)
    if not _can_access_assignment(assignment, user):
        raise not_found("assignment")
    master = db.get(RhapsodyMasterVersion, assignment.master_version_id)
    edition = db.get(RhapsodyEdition, master.edition_id)
    texts = {}
    for tr in db.execute(select(RhapsodySegmentTranslation).where(RhapsodySegmentTranslation.assignment_id == assignment.id)).scalars():
        if tr.current_version_id:
            texts[tr.segment_id] = db.get(RhapsodyTranslationVersion, tr.current_version_id).target_text
    try:
        pdf = _typeset_master(db, master, edition, texts, assignment.target_language)
    except Exception:
        raise ApiError(422, "pdf_render_failed", "HAN could not typeset the layout. Check the server rendering dependencies.")
    return _pdf_response(pdf, f"rhapsody-{edition.year}-{edition.month:02d}-{assignment.target_language}.pdf")
