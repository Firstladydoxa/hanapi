"""Admin-only language publishing profiles and secure font asset registry."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..deps import client_ip, get_current_user
from ..errors import ApiError, not_found
from ..models.db import Language, RhapsodyFontAsset, RhapsodyLanguageProfile, RhapsodyProfileFont, User
from ..security.permissions import ADMIN_ROLES, require_roles

router = APIRouter(prefix="/v1/rhapsody/publishing", tags=["rhapsody-publishing"])
ALLOWED = {".otf": "otf", ".ttf": "ttf", ".woff": "woff", ".woff2": "woff2"}
MAX_ROLES = {"body", "heading", "subheading", "scripture", "caption", "notes"}


def admin(request: Request, user: User = Depends(get_current_user)) -> User:
    require_roles(user, *ADMIN_ROLES, ip=client_ip(request))
    return user


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: str = Field(default="ltr", pattern="^(ltr|rtl)$")
    locale: str = Field(min_length=2, max_length=24)
    typography: dict[str, Any] = Field(default_factory=dict)
    localization: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] = Field(default_factory=dict)
    fonts: dict[str, str] = Field(default_factory=dict)
    status: str = Field(default="draft", pattern="^(draft|validated|active)$")


def _font_dir() -> Path:
    return Path(get_settings().rhapsody_font_storage_dir).resolve()


def _font_path(key: str) -> Path:
    base = _font_dir()
    target = (base / key).resolve()
    if base not in target.parents:
        raise ApiError(500, "font_storage_error", "The managed font path is invalid.")
    return target


def _font_out(f: RhapsodyFontAsset) -> dict:
    return {"id": str(f.id), "family": f.family, "style": f.style, "format": f.format,
            "byte_size": f.byte_size, "sha256": f.sha256, "license_name": f.license_name,
            "license_note": f.license_note, "coverage": f.coverage or {}, "created_at": f.created_at}


def _profile_out(db: Session, p: RhapsodyLanguageProfile, language: Language) -> dict:
    assignments = db.execute(select(RhapsodyProfileFont, RhapsodyFontAsset)
        .join(RhapsodyFontAsset, RhapsodyFontAsset.id == RhapsodyProfileFont.font_id)
        .where(RhapsodyProfileFont.profile_id == p.id)).all()
    return {"id": str(p.id), "language_code": p.language_code, "language_name": language.display_name,
            "direction": p.direction, "locale": p.locale, "typography": p.typography or {},
            "localization": p.localization or {}, "layout": p.layout or {}, "status": p.status, "version": p.version,
            "fonts": {a.role: _font_out(f) for a, f in assignments}, "updated_at": p.updated_at}


@router.get("/fonts")
def list_fonts(request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    rows = db.execute(select(RhapsodyFontAsset).order_by(RhapsodyFontAsset.family, RhapsodyFontAsset.style)).scalars()
    return [_font_out(f) for f in rows]


@router.post("/fonts", status_code=201)
async def upload_font(request: Request, file: UploadFile = File(...), family: str = Form(...),
                      style: str = Form("Regular"), license_name: str = Form(...),
                      license_note: Optional[str] = Form(None), user: User = Depends(admin),
                      db: Session = Depends(get_db)):
    filename = Path(file.filename or "").name
    ext = Path(filename).suffix.lower()
    fmt = ALLOWED.get(ext)
    if not fmt:
        raise ApiError(415, "unsupported_font", "Upload an OTF, TTF, WOFF or WOFF2 font file.")
    if not family.strip() or len(family) > 200 or not license_name.strip() or len(license_name) > 200:
        raise ApiError(422, "font_metadata_required", "Provide a font family and licence information.")
    data = await file.read(get_settings().rhapsody_max_font_bytes + 1)
    if not data or len(data) > get_settings().rhapsody_max_font_bytes:
        raise ApiError(413, "font_size", "The font file is empty or exceeds the 15 MB limit.")
    signatures = {"otf": (b"OTTO",), "ttf": (b"\x00\x01\x00\x00", b"true"),
                  "woff": (b"wOFF",), "woff2": (b"wOF2",)}
    if not data.startswith(signatures[fmt]):
        raise ApiError(422, "invalid_font", "The file signature does not match its font extension.")
    digest = hashlib.sha256(data).hexdigest()
    existing = db.execute(select(RhapsodyFontAsset).where(RhapsodyFontAsset.sha256 == digest)).scalar_one_or_none()
    if existing:
        raise ApiError(409, "font_exists", "This exact font file is already in the font library.")
    base = _font_dir()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    try: base.chmod(0o700)
    except OSError: pass
    key = f"{uuid.uuid4().hex}.{fmt}"
    target = _font_path(key)
    target.write_bytes(data)
    try: target.chmod(0o600)
    except OSError:
        target.unlink(missing_ok=True)
        raise ApiError(500, "font_storage_permissions", "The server could not secure the uploaded font.")
    row = RhapsodyFontAsset(family=family.strip(), style=style.strip()[:80] or "Regular", format=fmt,
        storage_key=key, sha256=digest, byte_size=len(data), license_name=license_name.strip(),
        license_note=(license_note or "").strip() or None, coverage={}, uploaded_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.record("rhapsody.font_uploaded", actor=user, object_type="rhapsody_font", object_id=row.id,
        details={"family": row.family, "format": fmt, "bytes": len(data)}, ip=client_ip(request))
    return _font_out(row)


@router.delete("/fonts/{font_id}", status_code=204)
def delete_font(font_id: str, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    try: fid = uuid.UUID(font_id)
    except ValueError: raise not_found("font")
    row = db.get(RhapsodyFontAsset, fid)
    if row is None: raise not_found("font")
    if db.execute(select(RhapsodyProfileFont.id).where(RhapsodyProfileFont.font_id == fid).limit(1)).first():
        raise ApiError(409, "font_in_use", "This font is assigned to a language profile. Reassign it before deleting.")
    key, family = row.storage_key, row.family
    db.delete(row)
    db.commit()
    _font_path(key).unlink(missing_ok=True)
    audit.record("rhapsody.font_deleted", actor=user, object_type="rhapsody_font", object_id=fid,
        details={"family": family}, ip=client_ip(request))


@router.get("/profiles")
def list_profiles(request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    langs = db.execute(select(Language).where(Language.active.is_(True)).order_by(Language.display_name)).scalars().all()
    profiles = {p.language_code: p for p in db.execute(select(RhapsodyLanguageProfile)).scalars()}
    return [_profile_out(db, profiles[l.code], l) if l.code in profiles else
            {"id": None, "language_code": l.code, "language_name": l.display_name, "direction": "ltr",
             "locale": l.code, "typography": {}, "localization": {}, "layout": {}, "status": "not_configured",
             "version": 0, "fonts": {}, "updated_at": None} for l in langs if l.code != "en"]


@router.put("/profiles/{language_code}")
def save_profile(language_code: str, body: ProfileIn, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    code = language_code.strip().lower().replace("_", "-")
    language = db.get(Language, code)
    if language is None or not language.active or code == "en":
        raise not_found("language")
    invalid_roles = set(body.fonts) - MAX_ROLES
    if invalid_roles:
        raise ApiError(422, "invalid_font_role", "One or more font roles are not supported.")
    font_ids: dict[str, uuid.UUID] = {}
    for role, raw_id in body.fonts.items():
        try: fid = uuid.UUID(raw_id)
        except ValueError: raise ApiError(422, "invalid_font", f"Invalid font selection for {role}.")
        if db.get(RhapsodyFontAsset, fid) is None:
            raise ApiError(422, "font_not_found", f"The selected {role} font is no longer available.")
        font_ids[role] = fid
    profile = db.execute(select(RhapsodyLanguageProfile).where(RhapsodyLanguageProfile.language_code == code)).scalar_one_or_none()
    if profile is None:
        profile = RhapsodyLanguageProfile(language_code=code, locale=body.locale, updated_by=user.id)
        db.add(profile)
        db.flush()
    profile.direction, profile.locale = body.direction, body.locale
    profile.typography, profile.localization, profile.layout = body.typography, body.localization, body.layout
    profile.status, profile.version, profile.updated_by = body.status, profile.version + 1, user.id
    db.query(RhapsodyProfileFont).filter(RhapsodyProfileFont.profile_id == profile.id).delete()
    for role, fid in font_ids.items():
        db.add(RhapsodyProfileFont(profile_id=profile.id, font_id=fid, role=role))
    db.commit()
    db.refresh(profile)
    audit.record("rhapsody.language_profile_saved", actor=user, object_type="rhapsody_language_profile",
        object_id=profile.id, details={"language": code, "version": profile.version, "font_roles": sorted(font_ids)}, ip=client_ip(request))
    return _profile_out(db, profile, language)
