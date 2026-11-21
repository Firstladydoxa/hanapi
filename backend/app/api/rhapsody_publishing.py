"""Admin-only language publishing profiles, font validation and layout preflight."""
from __future__ import annotations

import hashlib
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fontTools.ttLib import TTFont
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..deps import client_ip, get_current_user
from ..errors import ApiError, not_found
from ..models.db import (
    Language, RhapsodyAssignment, RhapsodyEdition, RhapsodyFontAsset, RhapsodyLanguageProfile,
    RhapsodyLayoutProof, RhapsodyMasterVersion, RhapsodyPermanentContent, RhapsodyProfileFont, RhapsodyProfileVersion,
    RhapsodyPublicationApproval,
    RhapsodySegment, RhapsodySection, RhapsodySegmentTranslation,
    RhapsodyTranslationVersion, User,
)
from ..security.permissions import ADMIN_ROLES, require_roles

router = APIRouter(prefix="/v1/rhapsody/publishing", tags=["rhapsody-publishing"])
ALLOWED = {".otf": "otf", ".ttf": "ttf", ".woff": "woff", ".woff2": "woff2"}
MAX_ROLES = {"body", "heading", "subheading", "scripture", "caption", "notes"}
LANGUAGE_SAMPLES = {
    "af": "Afrikaans: ŉ wêreld van genade, gebed en geloof.",
    "fr": "Français : À bientôt, cœur fidèle, Noël et prière.",
    "de": "Deutsch: Grüße, schöne Grüße, Straße, für Österreich.",
    "ar": "العربية: بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ",
}


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
            "license_note": f.license_note, "coverage": {k: v for k, v in (f.coverage or {}).items() if k != "codepoints"},
            "created_at": f.created_at}


def _profile_out(db: Session, p: RhapsodyLanguageProfile, language: Language) -> dict:
    assignments = db.execute(select(RhapsodyProfileFont, RhapsodyFontAsset)
        .join(RhapsodyFontAsset, RhapsodyFontAsset.id == RhapsodyProfileFont.font_id)
        .where(RhapsodyProfileFont.profile_id == p.id)).all()
    return {"id": str(p.id), "language_code": p.language_code, "language_name": language.display_name,
            "direction": p.direction, "locale": p.locale, "typography": p.typography or {},
            "localization": p.localization or {}, "layout": p.layout or {}, "status": p.status, "version": p.version,
            "fonts": {a.role: _font_out(f) for a, f in assignments}, "updated_at": p.updated_at}


def _inspect_font(data: bytes) -> dict:
    try:
        font = TTFont(BytesIO(data), lazy=True, recalcBBoxes=False, recalcTimestamp=False)
        cmap = font.getBestCmap() or {}
        names = font["name"].names if "name" in font else []
        family = next((n.toUnicode() for n in names if n.nameID == 1), None)
        subfamily = next((n.toUnicode() for n in names if n.nameID == 2), None)
        units = int(font["head"].unitsPerEm) if "head" in font else 1000
        fs_type = int(font["OS/2"].fsType) if "OS/2" in font else 0
        glyphs = sorted(int(cp) for cp in cmap.keys())
        scripts = {
            "latin": any(0x0041 <= cp <= 0x024F for cp in glyphs),
            "greek": any(0x0370 <= cp <= 0x03FF for cp in glyphs),
            "cyrillic": any(0x0400 <= cp <= 0x052F for cp in glyphs),
            "arabic": any(0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F for cp in glyphs),
            "hebrew": any(0x0590 <= cp <= 0x05FF for cp in glyphs),
            "devanagari": any(0x0900 <= cp <= 0x097F for cp in glyphs),
            "cjk": any(0x4E00 <= cp <= 0x9FFF for cp in glyphs),
        }
        result = {
            "family_name": family, "subfamily_name": subfamily, "glyph_count": len(glyphs),
            "codepoints": glyphs, "scripts": scripts, "units_per_em": units,
            "embedding_restricted": bool(fs_type & 0x0002),
            "no_subsetting": bool(fs_type & 0x0100), "fs_type": fs_type,
        }
        font.close()
        return result
    except Exception:
        raise ApiError(422, "font_parse_failed", "HAN could not parse this font. Upload a valid, supported font file.")


def _profile_fonts(db: Session, profile: RhapsodyLanguageProfile) -> dict[str, RhapsodyFontAsset]:
    rows = db.execute(select(RhapsodyProfileFont, RhapsodyFontAsset)
        .join(RhapsodyFontAsset, RhapsodyFontAsset.id == RhapsodyProfileFont.font_id)
        .where(RhapsodyProfileFont.profile_id == profile.id)).all()
    return {assignment.role: font for assignment, font in rows}


def font_faces(fonts: dict) -> tuple[str, dict[str, str]]:
    """@font-face CSS and role -> font stack for the manifest's fonts, after licence-flag and integrity checks."""
    from base64 import b64encode
    import re

    css: list[str] = []
    stacks: dict[str, str] = {}
    for role, info in fonts.items():
        if info.get("format") not in {"otf", "ttf"}:
            raise ApiError(409, "pdf_font_format_unsupported", f"The {role} font must be uploaded as OTF or TTF for PDF embedding.")
        permissions = info.get("coverage") or {}
        if permissions.get("embedding_restricted") or permissions.get("no_subsetting"):
            raise ApiError(409, "font_embedding_restricted", f"The {role} font licence flags do not permit this PDF embedding workflow.")
        path = _font_path(info["storage_key"])
        if not path.is_file():
            raise ApiError(409, "font_asset_unavailable", f"The {role} font is no longer available.")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != info["sha256"]:
            raise ApiError(409, "font_asset_integrity", f"The {role} font failed its integrity check.")
        mime, fmt = ("font/otf", "opentype") if info["format"] == "otf" else ("font/ttf", "truetype")
        family = "HAN_" + re.sub(r"[^A-Za-z0-9_]", "_", role)
        css.append(f"@font-face{{font-family:'{family}';src:url(data:{mime};base64,{b64encode(raw).decode('ascii')}) format('{fmt}');font-weight:400;font-style:normal;}}")
        stacks[role] = f"'{family}',serif"
    if "body" in stacks:
        stacks.setdefault("scripture", stacks["body"])
        stacks.setdefault("heading", stacks["body"])
    return "".join(css), stacks


@router.get("/fonts")
def list_fonts(request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    rows = db.execute(select(RhapsodyFontAsset).order_by(RhapsodyFontAsset.family, RhapsodyFontAsset.style)).scalars()
    usage = _font_usage(db)
    return [{**_font_out(f), "used_by": usage.get(f.id, [])} for f in rows]


def _font_usage(db: Session) -> dict:
    """font id -> [{language, role}] for every profile that uses it."""
    out: dict = {}
    for fid, code, role in db.execute(select(RhapsodyProfileFont.font_id, RhapsodyLanguageProfile.language_code, RhapsodyProfileFont.role)
            .join(RhapsodyLanguageProfile, RhapsodyLanguageProfile.id == RhapsodyProfileFont.profile_id)):
        out.setdefault(fid, []).append({"language": code, "role": role})
    return out


def _font_or_404(db: Session, font_id: str) -> RhapsodyFontAsset:
    row = db.get(RhapsodyFontAsset, uuid.UUID(font_id)) if _valid_uuid(font_id) else None
    if row is None:
        raise not_found("font")
    return row


class FontPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: Optional[str] = Field(default=None, min_length=1, max_length=200)
    style: Optional[str] = Field(default=None, min_length=1, max_length=80)
    license_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    license_note: Optional[str] = Field(default=None, max_length=1000)


@router.get("/fonts/{font_id}")
def get_font(font_id: str, user: User = Depends(admin), db: Session = Depends(get_db)):
    f = _font_or_404(db, font_id)
    return {**_font_out(f), "used_by": _font_usage(db).get(f.id, [])}


@router.patch("/fonts/{font_id}")
def update_font(font_id: str, body: FontPatch, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    f = _font_or_404(db, font_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ApiError(422, "nothing_to_update", "Change at least one field.")
    for k, v in changes.items():
        setattr(f, k, v.strip() if isinstance(v, str) else v)
        if k != "license_note" and not getattr(f, k):
            raise ApiError(422, "font_metadata_required", "Family, style and licence cannot be empty.")
    if "license_note" in changes:
        f.license_note = (f.license_note or "").strip() or None
    db.commit(); db.refresh(f)
    audit.record("rhapsody.font_updated", actor=user, object_type="rhapsody_font", object_id=f.id,
        details={"fields": sorted(changes)}, ip=client_ip(request))
    return {**_font_out(f), "used_by": _font_usage(db).get(f.id, [])}


@router.get("/fonts/{font_id}/file")
def font_file(font_id: str, user: User = Depends(admin), db: Session = Depends(get_db)):
    """Authenticated admin-only font bytes, used by the library to draw live specimens."""
    from fastapi.responses import FileResponse
    f = _font_or_404(db, font_id)
    path = _font_path(f.storage_key)
    if not path.is_file():
        raise not_found("font file")
    mime = {"otf": "font/otf", "ttf": "font/ttf", "woff": "font/woff", "woff2": "font/woff2"}[f.format]
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=3600"})


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
    signatures = {"otf": (b"OTTO", b"\x00\x01\x00\x00"), "ttf": (b"\x00\x01\x00\x00", b"true"),
                  "woff": (b"wOFF",), "woff2": (b"wOF2",)}
    if not data.startswith(signatures[fmt]):
        raise ApiError(422, "invalid_font", "The file signature does not match its font extension.")
    metadata = _inspect_font(data)
    digest = hashlib.sha256(data).hexdigest()
    if db.execute(select(RhapsodyFontAsset).where(RhapsodyFontAsset.sha256 == digest)).scalar_one_or_none():
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
        license_note=(license_note or "").strip() or None, coverage=metadata, uploaded_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.record("rhapsody.font_uploaded", actor=user, object_type="rhapsody_font", object_id=row.id,
        details={"family": row.family, "format": fmt, "bytes": len(data), "glyph_count": metadata["glyph_count"]}, ip=client_ip(request))
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
    db.delete(row); db.commit(); _font_path(key).unlink(missing_ok=True)
    audit.record("rhapsody.font_deleted", actor=user, object_type="rhapsody_font", object_id=fid,
        details={"family": family}, ip=client_ip(request))


def _snapshot(db: Session, profile: RhapsodyLanguageProfile, font_ids: dict, user: User) -> None:
    db.add(RhapsodyProfileVersion(profile_id=profile.id, version=profile.version, created_by=user.id, snapshot={
        "direction": profile.direction, "locale": profile.locale, "typography": profile.typography or {},
        "localization": profile.localization or {}, "layout": profile.layout or {}, "fonts": {r: str(i) for r, i in font_ids.items()}}))


def _profile_row(db: Session, code: str) -> tuple[RhapsodyLanguageProfile, Language]:
    code = code.strip().lower().replace("_", "-")
    language = db.get(Language, code)
    profile = db.execute(select(RhapsodyLanguageProfile).where(RhapsodyLanguageProfile.language_code == code)).scalar_one_or_none()
    if language is None or profile is None:
        raise not_found("language profile")
    return profile, language


@router.get("/profiles/{language_code}/versions")
def profile_versions(language_code: str, user: User = Depends(admin), db: Session = Depends(get_db)):
    profile, _ = _profile_row(db, language_code)
    rows = db.execute(select(RhapsodyProfileVersion, User.email).join(User, User.id == RhapsodyProfileVersion.created_by)
                      .where(RhapsodyProfileVersion.profile_id == profile.id).order_by(RhapsodyProfileVersion.version.desc())).all()
    return [{"version": v.version, "created_at": v.created_at, "created_by": email, "snapshot": v.snapshot} for v, email in rows]


@router.post("/profiles/{language_code}/restore/{version}")
def restore_profile_version(language_code: str, version: int, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    """Saves an earlier revision as a new draft revision; history is never rewritten."""
    profile, language = _profile_row(db, language_code)
    old = db.execute(select(RhapsodyProfileVersion).where(RhapsodyProfileVersion.profile_id == profile.id,
                                                          RhapsodyProfileVersion.version == version)).scalar_one_or_none()
    if old is None:
        raise not_found("profile version")
    snap = old.snapshot
    live_fonts = {str(i) for (i,) in db.execute(select(RhapsodyFontAsset.id))}
    font_ids = {r: uuid.UUID(i) for r, i in (snap.get("fonts") or {}).items() if i in live_fonts}
    profile.direction, profile.locale = snap["direction"], snap["locale"]
    profile.typography, profile.localization, profile.layout = snap["typography"], snap["localization"], snap["layout"]
    profile.status, profile.version, profile.updated_by = "draft", profile.version + 1, user.id
    db.query(RhapsodyProfileFont).filter(RhapsodyProfileFont.profile_id == profile.id).delete()
    for role, fid in font_ids.items():
        db.add(RhapsodyProfileFont(profile_id=profile.id, font_id=fid, role=role))
    db.flush()
    _snapshot(db, profile, font_ids, user)
    db.commit(); db.refresh(profile)
    audit.record("rhapsody.language_profile_restored", actor=user, object_type="rhapsody_language_profile", object_id=profile.id,
                 details={"language": profile.language_code, "from_version": version, "version": profile.version}, ip=client_ip(request))
    return _profile_out(db, profile, language)


@router.get("/profiles/{language_code}/specimen.pdf")
def profile_specimen(language_code: str, user: User = Depends(admin), db: Session = Depends(get_db)):
    """A one-page test sheet in the profile's own fonts and localized labels, so the admin can check accents and shaping."""
    from fastapi.responses import Response
    from html import escape
    from weasyprint import HTML

    profile, language = _profile_row(db, language_code)
    fonts = _profile_fonts(db, profile)
    info = {r: {"family": f.family, "format": f.format, "storage_key": f.storage_key, "sha256": f.sha256, "coverage": f.coverage or {}} for r, f in fonts.items()}
    css, stacks = font_faces(info) if info else ("", {})
    sample = LANGUAGE_SAMPLES.get(profile.language_code.split("-")[0], "The quick brown fox 0123456789 — “quoted text”.")
    loc = profile.localization or {}
    days = " · ".join(loc.get("weekdays") or []) or "—"
    months = " · ".join(loc.get("months") or []) or "—"
    body = stacks.get("body", "serif"); head = stacks.get("heading", "sans-serif"); scr = stacks.get("scripture", body)
    pt = float((profile.typography or {}).get("body_size_pt", 9.6))
    doc = (f"<html lang='{escape(profile.locale)}' dir='{profile.direction}'><head><meta charset='utf-8'><style>{css}"
           f"@page{{size:140mm 220mm;margin:12mm}}h1{{font:700 16pt {head}}}h2{{font:700 11pt {head};margin:6mm 0 1mm}}"
           f"p{{font:{pt}pt/1.4 {body};margin:0}}.s{{font:italic 700 {pt}pt/1.4 {scr}}}</style></head><body>"
           f"<h1>{escape(language.display_name)} — profile v{profile.version}</h1>"
           f"<h2>Body</h2><p>{escape(sample)}</p><h2>Scripture</h2><p class='s'>{escape(sample)}</p>"
           f"<h2>Weekdays</h2><p>{escape(days)}</p><h2>Months</h2><p>{escape(months)}</p></body></html>")
    return Response(HTML(string=doc).write_pdf(), media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="specimen.pdf"'})


@router.get("/production")
def edition_production(user: User = Depends(admin), db: Session = Depends(get_db)):
    """Per edition and language: translation progress against the language profile that will typeset it."""
    profiles = {p.language_code: p for p in db.execute(select(RhapsodyLanguageProfile)).scalars()}
    out = []
    for e in db.execute(select(RhapsodyEdition).order_by(RhapsodyEdition.year.desc(), RhapsodyEdition.month.desc()).limit(12)).scalars():
        if not e.active_master_version_id:
            out.append({"edition_id": str(e.id), "title": e.title, "master_active": False, "languages": []})
            continue
        rows = db.execute(select(RhapsodyAssignment, User.display_name).join(User, User.id == RhapsodyAssignment.translator_id)
                          .where(RhapsodyAssignment.master_version_id == e.active_master_version_id)).all()
        langs = []
        for a, name in rows:
            pr = profiles.get(a.target_language)
            rows_t = db.execute(select(RhapsodySegmentTranslation.current_version_id).where(RhapsodySegmentTranslation.assignment_id == a.id)).scalars().all()
            vids = [v for v in rows_t if v]
            unreviewed = db.execute(select(func.count()).select_from(RhapsodyTranslationVersion).where(
                RhapsodyTranslationVersion.id.in_(vids), RhapsodyTranslationVersion.origin == "ai")).scalar_one() if vids else 0
            proof = _latest_proof(db, a)
            language = db.get(Language, a.target_language)
            langs.append({"assignment_id": str(a.id), "language": a.target_language,
                          "language_name": language.display_name if language else a.target_language.upper(),
                          "translator": name, "status": a.status,
                          "translated": len(vids), "total": len(rows_t), "unreviewed": unreviewed,
                          "draft_status": a.draft_status, "has_proof": bool(proof and proof.pdf_sha256),
                          "created_at": a.created_at,
                          "profile_status": pr.status if pr else "not_configured", "profile_version": pr.version if pr else 0})
        out.append({"edition_id": str(e.id), "title": e.title, "master_active": True, "languages": langs})
    return out


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
        profile = RhapsodyLanguageProfile(language_code=code, locale=body.locale, updated_by=user.id, version=0)
        db.add(profile); db.flush()
    profile.direction, profile.locale = body.direction, body.locale
    # A save with an empty section never erases localization that was already imported or entered; it must be replaced, not blanked.
    kept = dict(body.localization or {})
    for key, old in (profile.localization or {}).items():
        new = kept.get(key)
        if old and (not new or (isinstance(new, list) and not any(str(x).strip() for x in new))):
            kept[key] = old
    profile.typography, profile.localization, profile.layout = body.typography, kept, body.layout
    profile.status, profile.version, profile.updated_by = "draft", profile.version + 1, user.id
    db.query(RhapsodyProfileFont).filter(RhapsodyProfileFont.profile_id == profile.id).delete()
    for role, fid in font_ids.items():
        db.add(RhapsodyProfileFont(profile_id=profile.id, font_id=fid, role=role))
    db.flush()
    _snapshot(db, profile, font_ids, user)
    db.commit(); db.refresh(profile)
    audit.record("rhapsody.language_profile_saved", actor=user, object_type="rhapsody_language_profile",
        object_id=profile.id, details={"language": code, "version": profile.version, "font_roles": sorted(font_ids)}, ip=client_ip(request))
    return _profile_out(db, profile, language)


@router.post("/profiles/{language_code}/validate")
def validate_profile(language_code: str, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    code = language_code.strip().lower().replace("_", "-")
    profile = db.execute(select(RhapsodyLanguageProfile).where(RhapsodyLanguageProfile.language_code == code)).scalar_one_or_none()
    language = db.get(Language, code)
    if profile is None or language is None: raise not_found("language profile")
    fonts = _profile_fonts(db, profile)
    sample = LANGUAGE_SAMPLES.get(code.split("-")[0], "The quick brown fox 0123456789 — “quoted text”.")
    checks = []
    required_roles = {"body", "heading"}
    missing_roles = sorted(required_roles - set(fonts))
    if missing_roles:
        checks.append({"code":"missing_required_fonts","severity":"error","message":f"Assign fonts for: {', '.join(missing_roles)}."})
    if profile.direction == "rtl" and code.split("-")[0] not in {"ar","he","fa","ur"}:
        checks.append({"code":"direction_review","severity":"warning","message":"RTL direction is selected for a language not in the built-in RTL language set. Verify the locale and shaping behaviour."})
    for role, font in fonts.items():
        codepoints = set((font.coverage or {}).get("codepoints", []))
        missing = sorted({ord(c) for c in sample if not c.isspace() and ord(c) not in codepoints})
        if missing:
            checks.append({"code":"missing_glyphs","severity":"error","role":role,"font_family":font.family,
                "missing_codepoints":[f"U+{cp:04X}" for cp in missing[:40]],"message":f"{font.family} is missing {len(missing)} sample character(s) for the {role} role."})
    has_errors = any(c["severity"] == "error" for c in checks)
    profile.status = "draft" if has_errors else "validated"
    db.commit()
    audit.record("rhapsody.language_profile_validated", actor=user, object_type="rhapsody_language_profile",
        object_id=profile.id, details={"language":code,"passed":not has_errors,"checks":len(checks)},ip=client_ip(request))
    return {"language_code":code,"status":profile.status,"sample_text":sample,"checks":checks,
            "note":"Character coverage is a preflight check only; it does not verify complex-script shaping or visual line breaking."}


@router.post("/profiles/{language_code}/activate")
def activate_profile(language_code: str, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    code = language_code.strip().lower().replace("_","-")
    profile = db.execute(select(RhapsodyLanguageProfile).where(RhapsodyLanguageProfile.language_code == code)).scalar_one_or_none()
    if profile is None: raise not_found("language profile")
    if profile.status != "validated":
        raise ApiError(409,"profile_not_validated","Run and pass language profile validation before activation.")
    profile.status = "active"; db.commit()
    audit.record("rhapsody.language_profile_activated",actor=user,object_type="rhapsody_language_profile",object_id=profile.id,
        details={"language":code,"version":profile.version},ip=client_ip(request))
    return {"language_code":code,"status":profile.status,"version":profile.version}


@router.post("/assignments/{assignment_id}/layout-proof")
def create_layout_proof(assignment_id: str, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    assignment = db.get(RhapsodyAssignment, uuid.UUID(assignment_id)) if _valid_uuid(assignment_id) else None
    if assignment is None: raise not_found("assignment")
    if assignment.status not in {"approved","published"}:
        raise ApiError(409,"translation_not_approved","The translation must be approved before generating a publishing proof.")
    profile = db.execute(select(RhapsodyLanguageProfile).where(RhapsodyLanguageProfile.language_code == assignment.target_language)).scalar_one_or_none()
    if profile is None or profile.status != "active":
        raise ApiError(409,"profile_not_active","Activate a validated language publishing profile before generating a proof.")
    fonts = _profile_fonts(db, profile)
    if not {"body","heading"}.issubset(fonts):
        raise ApiError(409,"profile_fonts_missing","The active profile must assign body and heading fonts.")
    master = db.get(RhapsodyMasterVersion, assignment.master_version_id)
    if master is None: raise not_found("master version")
    sections = list(db.execute(select(RhapsodySection).where(RhapsodySection.master_version_id == master.id).order_by(RhapsodySection.sequence)).scalars())
    segments = list(db.execute(select(RhapsodySegment).where(RhapsodySegment.master_version_id == master.id).order_by(RhapsodySegment.sequence)).scalars())
    translations = {t.segment_id:t for t in db.execute(select(RhapsodySegmentTranslation).where(RhapsodySegmentTranslation.assignment_id == assignment.id)).scalars()}
    version_ids = [t.current_version_id for t in translations.values() if t.current_version_id]
    versions = {v.id:v for v in db.execute(select(RhapsodyTranslationVersion).where(RhapsodyTranslationVersion.id.in_(version_ids))).scalars()} if version_ids else {}
    blocks=[]; missing=[]
    for seg in segments:
        tr=translations.get(seg.id); version=versions.get(tr.current_version_id) if tr and tr.current_version_id else None
        if version is None: missing.append(seg.stable_key); continue
        blocks.append({"key":seg.stable_key,"section_id":str(seg.section_id),"role":(seg.metadata_json or {}).get("role","body"),
                       "text":version.target_text,"meta":{k: v for k, v in (seg.metadata_json or {}).items() if k != "runs"},"source_length":len(seg.source_text),"target_length":len(version.target_text)})
    if missing:
        raise ApiError(409,"translation_incomplete",f"{len(missing)} translated segments are missing; complete the assignment before proofing.")
    font_manifest={}
    for role,font in fonts.items():
        path=_font_path(font.storage_key)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=font.sha256:
            raise ApiError(409,"font_asset_unavailable",f"The assigned {role} font failed its storage integrity check.")
        font_manifest[role]={"family":font.family,"style":font.style,"format":font.format,"sha256":font.sha256,
                             "license":font.license_name,"storage_key":font.storage_key,"coverage":font.coverage or {}}
    layout_cfg=profile.layout or {}
    try:
        page_width=float(layout_cfg.get("page_width_mm",140))
        page_height=float(layout_cfg.get("page_height_mm",220))
        margin=float(layout_cfg.get("margin_mm",12))
        inner=float(layout_cfg.get("margin_inner_mm",margin)); outer=float(layout_cfg.get("margin_outer_mm",margin))
        font_size=float((profile.typography or {}).get("body_size_pt",9.6))
    except (TypeError, ValueError):
        raise ApiError(422,"invalid_layout_settings","Page dimensions and typography settings must be numeric.")
    if not (90 <= page_width <= 400 and 120 <= page_height <= 500 and 4 <= margin <= 40 and 4 <= inner <= 40 and 4 <= outer <= 40 and 6 <= font_size <= 24):
        raise ApiError(422,"invalid_layout_settings","Page dimensions, margins or body font size are outside supported publishing limits.")
    usable_width=max(30,page_width-2*margin); usable_height=max(50,page_height-2*margin)
    chars_per_line=max(20,int(usable_width*2.4/max(font_size,6)))
    lines_per_page=max(12,int(usable_height*2.0/max(font_size*1.35,1)))
    for block in blocks:
        block["estimated_lines"]=max(1,(len(block["text"])+chars_per_line-1)//chars_per_line)
    total_lines=sum(b["estimated_lines"]+1 for b in blocks)
    page_estimate=max(1,(total_lines+lines_per_page-1)//lines_per_page)
    fingerprint=hashlib.sha256("|".join(f"{b['key']}:{hashlib.sha256(b['text'].encode()).hexdigest()}" for b in blocks).encode()).hexdigest()
    manifest={"language":assignment.target_language,"locale":profile.locale,"direction":profile.direction,"profile_version":profile.version,
        "page":{"width_mm":page_width,"height_mm":page_height,"margin_mm":margin,"margin_inner_mm":inner,"margin_outer_mm":outer},"typography":profile.typography or {},
        "fonts":font_manifest,"sections":[{"id":str(s.id),"key":s.stable_key,"type":s.section_type,"sequence":s.sequence,"day":s.day_number,"formatting":s.formatting or {}} for s in sections],
        "blocks":blocks,"pagination":{"estimated_pages":page_estimate,"method":"character-count preflight estimate; not final typeset pagination"},
        "renderer_contract":{"text_reflow":True,"repaginate":True,"embed_fonts":True,"respect_direction":profile.direction,
                             "font_storage":"private server-side assets; resolve by storage_key and verify sha256"},
        "localization":{k:v for k,v in (profile.localization or {}).items() if k!="book_names"},
        "book_names":(profile.localization or {}).get("book_names") or {},
        "permanent":permanent_content(db,assignment.target_language,approved_only=True)}
    proof=RhapsodyLayoutProof(assignment_id=assignment.id,profile_version=profile.version,translation_fingerprint=fingerprint,
        manifest=manifest,created_by=user.id)
    db.add(proof); db.commit(); db.refresh(proof)
    audit.record("rhapsody.layout_proof_created",actor=user,object_type="rhapsody_layout_proof",object_id=proof.id,
        details={"assignment_id":str(assignment.id),"language":assignment.target_language,"profile_version":profile.version,"estimated_pages":page_estimate},ip=client_ip(request))
    return {"id":str(proof.id),"assignment_id":str(assignment.id),"profile_version":profile.version,
            "translation_fingerprint":fingerprint,"manifest":manifest,"created_at":proof.created_at}


def _valid_uuid(value: str) -> bool:
    try: uuid.UUID(value); return True
    except ValueError: return False


@router.post("/layout-proofs/{proof_id}/pdf")
def render_layout_proof_pdf(proof_id: str, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    """Generate a reflowable, font-embedded PDF proof using WeasyPrint/Pango.

    This is a native HAN layout proof, not an exact InDesign/IDML reproduction.
    """
    from ..rhapsody_typeset import typeset_pdf
    from .rhapsody import edition_images

    try:
        pid = uuid.UUID(proof_id)
    except ValueError:
        raise not_found("layout proof")
    proof = db.get(RhapsodyLayoutProof, pid)
    if proof is None:
        raise not_found("layout proof")
    manifest = proof.manifest or {}
    if not manifest.get("blocks"):
        raise ApiError(409, "empty_layout_proof", "This layout proof contains no content.")
    font_css, role_fonts = font_faces(manifest.get("fonts") or {})
    page = manifest.get("page") or {}
    assignment = db.get(RhapsodyAssignment, proof.assignment_id)
    master = db.get(RhapsodyMasterVersion, assignment.master_version_id) if assignment else None
    edition = db.get(RhapsodyEdition, master.edition_id) if master else None
    try:
        pdf = typeset_pdf(manifest.get("sections") or [], manifest.get("blocks") or [],
            title=f"Rhapsody of Realities {manifest.get('language')}", year=edition.year if edition else 0, month=edition.month if edition else 0,
            direction=manifest.get("direction", "ltr"), lang=str(manifest.get("locale") or manifest.get("language") or "en"),
            page_mm=(float(page.get("width_mm", 140)), float(page.get("height_mm", 220))), margin_mm=float(page.get("margin_mm", 12)),
            inner_mm=float(page.get("margin_inner_mm", page.get("margin_mm", 12))), outer_mm=float(page.get("margin_outer_mm", page.get("margin_mm", 12))),
            body_pt=float((manifest.get("typography") or {}).get("body_size_pt", 9.6)), font_css=font_css, role_fonts=role_fonts,
            month_label=edition.title if edition else None,
            localization=manifest.get("localization") or {}, permanent=manifest.get("permanent") or {},
            book_names=manifest.get("book_names") or {}, images=edition_images(edition.id) if edition else {},
            title_pt=float((manifest.get("typography") or {}).get("heading_size_pt", 13)),
            scripture_pt=float((manifest.get("typography") or {}).get("scripture_size_pt", 9)))
    except Exception:
        raise ApiError(422, "pdf_render_failed", "The layout proof could not be typeset. Check the selected fonts and server rendering dependencies.")
    digest = hashlib.sha256(pdf).hexdigest()
    base = Path(get_settings().rhapsody_storage_dir).resolve()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = f"layout-proofs/{proof.id}/{uuid.uuid4().hex}.pdf"
    target = (base / key).resolve()
    if base not in target.parents:
        raise ApiError(500, "storage_error", "The generated PDF path is invalid.")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.write_bytes(pdf)
    try:
        target.chmod(0o600); target.parent.chmod(0o700)
    except OSError:
        target.unlink(missing_ok=True)
        raise ApiError(500, "storage_permissions", "The server could not secure the generated PDF.")
    proof.pdf_storage_key, proof.pdf_sha256, proof.pdf_byte_size = key, digest, len(pdf)
    db.commit()
    audit.record("rhapsody.layout_pdf_rendered", actor=user, object_type="rhapsody_layout_proof", object_id=proof.id,
        details={"language":manifest.get("language"),"bytes":len(pdf),"sha256":digest},ip=client_ip(request))
    return {"proof_id":str(proof.id),"pdf_ready":True,"byte_size":len(pdf),"sha256":digest,
            "note":"Reflowable HAN proof PDF. Final InDesign style-token mapping and print-production approval remain separate checks."}


@router.get("/layout-proofs/{proof_id}/pdf")
def download_layout_proof_pdf(proof_id: str, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    try:
        pid = uuid.UUID(proof_id)
    except ValueError:
        raise not_found("layout proof")
    proof = db.get(RhapsodyLayoutProof, pid)
    if proof is None or not proof.pdf_storage_key:
        raise not_found("layout PDF")
    base = Path(get_settings().rhapsody_storage_dir).resolve()
    target = (base / proof.pdf_storage_key).resolve()
    if base not in target.parents or not target.is_file():
        raise not_found("layout PDF")
    data = target.read_bytes()
    if hashlib.sha256(data).hexdigest() != proof.pdf_sha256:
        raise ApiError(409, "pdf_integrity_failed", "The stored PDF failed its integrity check.")
    return FileResponse(target, media_type="application/pdf", filename=f"rhapsody-{proof_id}.pdf")


# ------------------------------------------------------------------------------------------ permanent content library
PERMANENT_KEYS = ["intro.heading", "intro.paragraphs", "howto.heading", "howto.items", "intro.closing", "intro.signoff",
                  "personal.title", "personal.fields", "personal.goals", "title.name", "title.sub", "copyright.lines",
                  "salvation.items", "authors.items", "backtext.items", "labels.table"]
RENDERED_KEYS = [k for k in PERMANENT_KEYS if k != "labels.table"]


def permanent_content(db: Session, language: str, approved_only: bool = True) -> dict[str, list[str]]:
    q = select(RhapsodyPermanentContent).where(RhapsodyPermanentContent.language_code == language)
    if approved_only:
        q = q.where(RhapsodyPermanentContent.status == "approved")
    return {r.key: list(r.items or []) for r in db.execute(q).scalars() if r.key in RENDERED_KEYS}


class PermanentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[str] = Field(max_length=200)


def _perm_out(r: RhapsodyPermanentContent) -> dict:
    return {"key": r.key, "items": r.items or [], "status": r.status, "updated_at": r.updated_at}


def _lang_code(db: Session, language_code: str) -> str:
    code = language_code.strip().lower().replace("_", "-")
    language = db.get(Language, code)
    if language is None or not language.active or code == "en":
        raise not_found("language")
    return code


def _upsert_permanent(db: Session, code: str, key: str, items: list[str], user: User) -> RhapsodyPermanentContent:
    row = db.execute(select(RhapsodyPermanentContent).where(RhapsodyPermanentContent.language_code == code,
                                                            RhapsodyPermanentContent.key == key)).scalar_one_or_none()
    items = [str(i).strip()[:4000] for i in items if str(i).strip()]
    if row is None:
        row = RhapsodyPermanentContent(language_code=code, key=key, items=items, status="draft", updated_by=user.id)
        db.add(row)
    else:
        row.items, row.status, row.updated_by = items, "draft", user.id
    return row


@router.get("/profiles/{language_code}/permanent")
def list_permanent(language_code: str, user: User = Depends(admin), db: Session = Depends(get_db)):
    code = _lang_code(db, language_code)
    rows = {r.key: r for r in db.execute(select(RhapsodyPermanentContent).where(RhapsodyPermanentContent.language_code == code)).scalars()}
    return [_perm_out(rows[k]) if k in rows else {"key": k, "items": [], "status": "empty", "updated_at": None} for k in PERMANENT_KEYS]


@router.put("/profiles/{language_code}/permanent/{key}")
def save_permanent(language_code: str, key: str, body: PermanentIn, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    code = _lang_code(db, language_code)
    if key not in PERMANENT_KEYS:
        raise ApiError(422, "invalid_permanent_key", "This permanent content item is not supported.")
    row = _upsert_permanent(db, code, key, body.items, user)
    db.commit(); db.refresh(row)
    audit.record("rhapsody.permanent_content_saved", actor=user, object_type="rhapsody_permanent_content", object_id=row.id,
                 details={"language": code, "key": key}, ip=client_ip(request))
    return _perm_out(row)


@router.post("/profiles/{language_code}/permanent/{key}/approve")
def approve_permanent(language_code: str, key: str, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    code = _lang_code(db, language_code)
    row = db.execute(select(RhapsodyPermanentContent).where(RhapsodyPermanentContent.language_code == code,
                                                            RhapsodyPermanentContent.key == key)).scalar_one_or_none()
    if row is None or not row.items:
        raise not_found("permanent content")
    row.status, row.updated_by = "approved", user.id
    db.commit(); db.refresh(row)
    audit.record("rhapsody.permanent_content_approved", actor=user, object_type="rhapsody_permanent_content", object_id=row.id,
                 details={"language": code, "key": key}, ip=client_ip(request))
    return _perm_out(row)


@router.post("/profiles/{language_code}/import-sheet")
async def import_resource_sheet(language_code: str, request: Request, file: UploadFile = File(...), apply: bool = Form(False),
                                user: User = Depends(admin), db: Session = Depends(get_db)):
    """Reads TNI's per-language 'additional information' sheet. Without `apply` it only previews what would be imported."""
    from ..legacy_doc import extract_paragraphs, is_legacy_doc
    from ..rhapsody_resources import ResourceSheetError, parse_sheet

    code = _lang_code(db, language_code)
    data = await file.read(10 * 1024 * 1024 + 1)
    if not data or len(data) > 10 * 1024 * 1024:
        raise ApiError(422, "invalid_sheet", "Upload a language information sheet under 10 MB.")
    try:
        if is_legacy_doc(data):
            paragraphs = extract_paragraphs(data)
        else:
            from ..rhapsody_layout import _paragraphs
            paragraphs = [p["text"] for p in _paragraphs(data)]
        parsed = parse_sheet(paragraphs)
    except ResourceSheetError as exc:
        raise ApiError(422, "invalid_sheet", str(exc))
    except Exception:
        raise ApiError(422, "invalid_sheet", "HAN could not read this document. Upload the .doc or .docx information sheet.")
    summary = {"months": len(parsed["months"]), "weekdays": len(parsed["weekdays"]), "books": len(parsed["book_names"]),
               "labels": sorted(parsed["labels"]), "permanent": {k: len(v) for k, v in parsed["permanent"].items()},
               "warnings": parsed["warnings"]}
    if not apply:
        return {"applied": False, **summary, "preview": parsed["permanent"]}
    profile = db.execute(select(RhapsodyLanguageProfile).where(RhapsodyLanguageProfile.language_code == code)).scalar_one_or_none()
    if profile is None:
        raise ApiError(409, "profile_missing", "Save the language profile (General tab) before importing its information sheet.")
    loc = dict(profile.localization or {})
    if parsed["months"]: loc["months"] = parsed["months"]
    if parsed["weekdays"]: loc["weekdays"] = parsed["weekdays"]
    if parsed["labels"]: loc["labels"] = {**(loc.get("labels") or {}), **parsed["labels"]}
    if parsed["book_names"]: loc["book_names"] = parsed["book_names"]
    profile.localization, profile.status, profile.version, profile.updated_by = loc, "draft", profile.version + 1, user.id
    font_ids = {r.role: r.font_id for r in db.execute(select(RhapsodyProfileFont).where(RhapsodyProfileFont.profile_id == profile.id)).scalars()}
    db.flush()
    _snapshot(db, profile, font_ids, user)
    for key, items in parsed["permanent"].items():
        if key in PERMANENT_KEYS and items:
            _upsert_permanent(db, code, key, items, user)
    db.commit()
    audit.record("rhapsody.resource_sheet_imported", actor=user, object_type="rhapsody_language_profile", object_id=profile.id,
                 details={"language": code, "version": profile.version, "books": summary["books"]}, ip=client_ip(request))
    return {"applied": True, "profile_version": profile.version, **summary}


# ------------------------------------------------------------------------------------------------ proofing and approval
def _current_fingerprint(db: Session, assignment: RhapsodyAssignment) -> Optional[str]:
    segments = list(db.execute(select(RhapsodySegment).where(RhapsodySegment.master_version_id == assignment.master_version_id)
                               .order_by(RhapsodySegment.sequence)).scalars())
    parts = []
    for seg in segments:
        tr = db.execute(select(RhapsodySegmentTranslation).where(RhapsodySegmentTranslation.assignment_id == assignment.id,
                                                                  RhapsodySegmentTranslation.segment_id == seg.id)).scalar_one_or_none()
        version = db.get(RhapsodyTranslationVersion, tr.current_version_id) if tr and tr.current_version_id else None
        if version is None:
            return None
        parts.append(f"{seg.stable_key}:{hashlib.sha256(version.target_text.encode()).hexdigest()}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Optional[str] = Field(default=None, max_length=2000)


def _assignment(db: Session, assignment_id: str) -> RhapsodyAssignment:
    a = db.get(RhapsodyAssignment, uuid.UUID(assignment_id)) if _valid_uuid(assignment_id) else None
    if a is None:
        raise not_found("assignment")
    return a


def _latest_proof(db: Session, assignment: RhapsodyAssignment) -> Optional[RhapsodyLayoutProof]:
    return db.execute(select(RhapsodyLayoutProof).where(RhapsodyLayoutProof.assignment_id == assignment.id,
                                                       RhapsodyLayoutProof.pdf_storage_key.is_not(None))
                      .order_by(RhapsodyLayoutProof.created_at.desc()).limit(1)).scalar_one_or_none()


@router.get("/assignments/{assignment_id}/publication")
def publication_state(assignment_id: str, user: User = Depends(admin), db: Session = Depends(get_db)):
    a = _assignment(db, assignment_id)
    proof = _latest_proof(db, a)
    history = db.execute(select(RhapsodyPublicationApproval, User.display_name).join(User, User.id == RhapsodyPublicationApproval.decided_by)
                         .where(RhapsodyPublicationApproval.assignment_id == a.id)
                         .order_by(RhapsodyPublicationApproval.created_at.desc())).all()
    current = _current_fingerprint(db, a)
    return {"assignment_status": a.status,
            "proof": None if proof is None else {"id": str(proof.id), "profile_version": proof.profile_version, "sha256": proof.pdf_sha256,
                                                 "created_at": proof.created_at, "stale": current != proof.translation_fingerprint},
            "history": [{"decision": r.decision, "note": r.note, "by": n, "profile_version": r.profile_version,
                         "proof_id": str(r.proof_id), "pdf_sha256": r.pdf_sha256, "created_at": r.created_at} for r, n in history]}


def _decide(db: Session, request: Request, user: User, assignment_id: str, decision: str, note: Optional[str]) -> dict:
    a = _assignment(db, assignment_id)
    if a.status not in {"approved", "published", "changes_requested"}:
        raise ApiError(409, "translation_not_approved", "The translation must be approved before it can be proofed for publication.")
    proof = _latest_proof(db, a)
    if proof is None:
        raise ApiError(409, "proof_not_rendered", "Generate the proof PDF before approving or returning it.")
    if decision == "approved":
        if _current_fingerprint(db, a) != proof.translation_fingerprint:
            raise ApiError(409, "proof_stale", "The translation changed after this proof was generated. Generate a new proof.")
        profile = db.execute(select(RhapsodyLanguageProfile).where(RhapsodyLanguageProfile.language_code == a.target_language)).scalar_one_or_none()
        if profile is None or profile.status != "active" or profile.version != proof.profile_version:
            raise ApiError(409, "profile_changed", "The language profile changed after this proof was generated. Generate a new proof.")
        path = (Path(get_settings().rhapsody_storage_dir).resolve() / proof.pdf_storage_key)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != proof.pdf_sha256:
            raise ApiError(409, "pdf_integrity_failed", "The stored proof PDF failed its integrity check.")
    a.status = "published" if decision == "approved" else "changes_requested"
    row = RhapsodyPublicationApproval(assignment_id=a.id, proof_id=proof.id, decision=decision, note=(note or "").strip() or None,
        profile_version=proof.profile_version, translation_fingerprint=proof.translation_fingerprint, pdf_sha256=proof.pdf_sha256, decided_by=user.id)
    db.add(row); db.commit()
    audit.record(f"rhapsody.publication_{decision}", actor=user, object_type="rhapsody_assignment", object_id=a.id,
                 details={"language": a.target_language, "proof_id": str(proof.id), "sha256": proof.pdf_sha256}, ip=client_ip(request))
    from .rhapsody import alert_assignment
    if decision == "approved":
        alert_assignment(db, a, "published", "{lang} approved for publication", note, translator=True, admins=True, level="success", exclude=user.id)
    else:
        alert_assignment(db, a, "changes_requested", "Layout changes requested on {lang}", note, translator=True, level="warning", exclude=user.id)
    return {"assignment_status": a.status, "decision": decision, "proof_id": str(proof.id)}


@router.post("/assignments/{assignment_id}/publication/approve")
def approve_publication(assignment_id: str, request: Request, body: DecisionIn = DecisionIn(), user: User = Depends(admin), db: Session = Depends(get_db)):
    return _decide(db, request, user, assignment_id, "approved", body.note)


@router.post("/assignments/{assignment_id}/publication/request-changes")
def request_publication_changes(assignment_id: str, request: Request, body: DecisionIn, user: User = Depends(admin), db: Session = Depends(get_db)):
    if not (body.note or "").strip():
        raise ApiError(422, "note_required", "Explain what must change.")
    return _decide(db, request, user, assignment_id, "changes_requested", body.note)
