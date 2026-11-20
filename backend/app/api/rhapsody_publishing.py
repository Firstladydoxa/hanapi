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
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..deps import client_ip, get_current_user
from ..errors import ApiError, not_found
from ..models.db import (
    Language, RhapsodyAssignment, RhapsodyFontAsset, RhapsodyLanguageProfile,
    RhapsodyLayoutProof, RhapsodyMasterVersion, RhapsodyProfileFont,
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
            "license_note": f.license_note, "coverage": f.coverage or {}, "created_at": f.created_at}


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
        result = {"family_name": family, "subfamily_name": subfamily, "glyph_count": len(glyphs),
                  "codepoints": glyphs, "scripts": scripts, "units_per_em": units}
        font.close()
        return result
    except Exception:
        raise ApiError(422, "font_parse_failed", "HAN could not parse this font. Upload a valid, supported font file.")


def _profile_fonts(db: Session, profile: RhapsodyLanguageProfile) -> dict[str, RhapsodyFontAsset]:
    rows = db.execute(select(RhapsodyProfileFont, RhapsodyFontAsset)
        .join(RhapsodyFontAsset, RhapsodyFontAsset.id == RhapsodyProfileFont.font_id)
        .where(RhapsodyProfileFont.profile_id == profile.id)).all()
    return {assignment.role: font for assignment, font in rows}


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
    signatures = {"otf": (b"OTTO",), "ttf": (b"\\x00\\x01\\x00\\x00", b"true"),
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
        db.add(profile); db.flush()
    profile.direction, profile.locale = body.direction, body.locale
    profile.typography, profile.localization, profile.layout = body.typography, body.localization, body.layout
    profile.status, profile.version, profile.updated_by = "draft", profile.version + 1, user.id
    db.query(RhapsodyProfileFont).filter(RhapsodyProfileFont.profile_id == profile.id).delete()
    for role, fid in font_ids.items():
        db.add(RhapsodyProfileFont(profile_id=profile.id, font_id=fid, role=role))
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
                       "text":version.target_text,"source_length":len(seg.source_text),"target_length":len(version.target_text)})
    if missing:
        raise ApiError(409,"translation_incomplete",f"{len(missing)} translated segments are missing; complete the assignment before proofing.")
    font_manifest={}
    for role,font in fonts.items():
        path=_font_path(font.storage_key)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=font.sha256:
            raise ApiError(409,"font_asset_unavailable",f"The assigned {role} font failed its storage integrity check.")
        font_manifest[role]={"family":font.family,"style":font.style,"format":font.format,"sha256":font.sha256,
                             "license":font.license_name,"storage_key":font.storage_key}
    layout_cfg=profile.layout or {}
    page_width=float(layout_cfg.get("page_width_mm",148)); page_height=float(layout_cfg.get("page_height_mm",210))
    margin=float(layout_cfg.get("margin_mm",14)); font_size=float((profile.typography or {}).get("body_size_pt",10.5))
    if not (90 <= page_width <= 400 and 120 <= page_height <= 500 and 4 <= margin <= 40 and 6 <= font_size <= 24):
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
        "page":{"width_mm":page_width,"height_mm":page_height,"margin_mm":margin},"typography":profile.typography or {},
        "fonts":font_manifest,"sections":[{"id":str(s.id),"key":s.stable_key,"type":s.section_type,"sequence":s.sequence} for s in sections],
        "blocks":blocks,"pagination":{"estimated_pages":page_estimate,"method":"character-count preflight estimate; not final typeset pagination"},
        "renderer_contract":{"text_reflow":True,"repaginate":True,"embed_fonts":True,"respect_direction":profile.direction,
                             "font_storage":"private server-side assets; resolve by storage_key and verify sha256"}}
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
