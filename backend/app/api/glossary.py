"""Per-language glossary. Any signed-in user may read; only that language's team leader (or an administrator) may change it."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, glossary
from ..database import get_db
from ..deps import client_ip, get_current_user, get_user_no_csrf
from ..errors import ApiError, forbidden, not_found
from ..models import schemas as S
from ..models.db import GlossaryEntry, GlossaryLead, Language, User
from ..security.permissions import ADMIN_ROLES, parse_uuid

router = APIRouter(prefix="/v1/glossary", tags=["glossary"])
MAX_IMPORT = 2 * 1024 * 1024
MAX_ROWS = 5000


class EntryIn(S.Req):
    source_text: str = Field(min_length=1, max_length=2000)
    target_text: str = Field(min_length=1, max_length=4000)
    kind: Optional[str] = Field(default=None, max_length=16)
    notes: Optional[str] = Field(default=None, max_length=2000)


class EntryPatch(S.Req):
    source_text: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    target_text: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    kind: Optional[str] = Field(default=None, max_length=16)
    notes: Optional[str] = Field(default=None, max_length=2000)


class EntryOut(S.Public):
    id: str
    language: str
    source_text: str
    target_text: str
    kind: str
    notes: Optional[str] = None
    updated_at: datetime
    updated_by: Optional[str] = None


class EntryPage(S.Public):
    total: int
    items: List[EntryOut]


class LanguageCard(S.Public):
    code: str
    name: str
    native_name: Optional[str] = None
    entries: int
    can_manage: bool
    leaders: List[str] = []


class Overview(S.Public):
    total_entries: int
    languages_with_entries: int
    managed_languages: int
    can_manage_any: bool
    is_admin: bool
    languages: List[LanguageCard]
    recent: List[EntryOut]


class ImportResult(S.Public):
    added: int
    updated: int
    skipped: int
    errors: List[str] = []


class LeadOut(S.Public):
    user_id: str
    display_name: str
    email: str
    languages: List[str]


class LeadIn(S.Req):
    languages: List[str] = Field(max_length=100)


def _names(db: Session, ids) -> dict:
    ids = {i for i in ids if i}
    return {u.id: u.display_name for u in db.execute(select(User).where(User.id.in_(ids))).scalars()} if ids else {}


def _out(e: GlossaryEntry, names: dict) -> EntryOut:
    return EntryOut(id=str(e.id), language=e.language, source_text=e.source_text, target_text=e.target_text, kind=e.kind, notes=e.notes,
                    updated_at=e.updated_at, updated_by=names.get(e.updated_by))


def _language(db: Session, code: str) -> Language:
    lang = db.get(Language, code.strip().lower().replace("_", "-"))
    if lang is None or not lang.active or lang.code == "en":
        raise not_found("language")
    return lang


def _reader(db: Session, user: User, code: str) -> Language:
    lang = _language(db, code)
    if not glossary.can_read(user, lang.code):
        raise forbidden("Translators can only open the glossary of their own language of expertise.")
    return lang


def _writer(db: Session, user: User, code: str, request: Request) -> Language:
    lang = _language(db, code)
    if not glossary.can_manage(db, user, lang.code):
        audit.record("access.denied", actor=user, outcome="denied", object_type="glossary", object_id=lang.code, ip=client_ip(request))
        raise forbidden("Only this language's team leader can change its glossary.")
    return lang


def _check_kind(kind: Optional[str]) -> None:
    if kind is not None and kind not in glossary.KINDS:
        raise ApiError(422, "invalid_kind", "Kind must be word, expression or sentence.")


@router.get("/overview", response_model=Overview)
def overview(user: User = Depends(get_user_no_csrf), db: Session = Depends(get_db)):
    mine = glossary.managed_languages(db, user)
    visible = glossary.readable_languages(user)
    counts, leads = glossary.counts(db), glossary.leaders(db)
    if visible is not None:
        counts = {k: v for k, v in counts.items() if k in visible}
    langs = [l for l in db.execute(select(Language).where(Language.active.is_(True), Language.code != "en").order_by(Language.display_name)).scalars()
             if visible is None or l.code in visible]
    cards = [LanguageCard(code=l.code, name=l.display_name, native_name=l.native_name, entries=counts.get(l.code, 0),
                          can_manage=mine is None or l.code in mine, leaders=leads.get(l.code, [])) for l in langs]
    recent_q = select(GlossaryEntry).order_by(GlossaryEntry.updated_at.desc()).limit(8)
    if visible is not None:
        recent_q = recent_q.where(GlossaryEntry.language.in_(visible))
    recent = list(db.execute(recent_q).scalars())
    names = _names(db, [e.updated_by for e in recent])
    return Overview(total_entries=sum(counts.values()), languages_with_entries=len(counts), managed_languages=sum(1 for c in cards if c.can_manage),
                    can_manage_any=any(c.can_manage for c in cards), is_admin=user.role in ADMIN_ROLES, languages=cards, recent=[_out(e, names) for e in recent])


@router.get("/leads", response_model=List[LeadOut])
def list_leads(user: User = Depends(get_user_no_csrf), db: Session = Depends(get_db)):
    if user.role not in ADMIN_ROLES:
        raise forbidden()
    by_user: dict = {}
    for l in db.execute(select(GlossaryLead)).scalars():
        by_user.setdefault(l.user_id, []).append(l.language)
    out = []
    for u in db.execute(select(User).where(User.role == "team_leader", User.status == "active").order_by(User.display_name)).scalars():
        out.append(LeadOut(user_id=str(u.id), display_name=u.display_name, email=u.email, languages=sorted(by_user.get(u.id, []))))
    return out


@router.put("/leads/{user_id}", response_model=LeadOut)
def set_leads(user_id: str, body: LeadIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ADMIN_ROLES:
        raise forbidden()
    target = db.get(User, parse_uuid(user_id, "user"))
    if target is None or target.role != "team_leader":
        raise ApiError(422, "not_team_leader", "Only users with the Team leader role can be assigned languages.")
    codes = [_language(db, c).code for c in body.languages]
    glossary.set_leads(db, target.id, codes)
    db.commit()
    audit.record("glossary.leads_set", actor=user, object_type="user", object_id=target.id, details={"languages": codes}, ip=client_ip(request))
    return LeadOut(user_id=str(target.id), display_name=target.display_name, email=target.email, languages=sorted(set(codes)))


@router.get("/{language}/entries", response_model=EntryPage)
def list_entries(language: str, q: str = "", kind: Optional[str] = None, limit: int = 50, offset: int = 0,
                 user: User = Depends(get_user_no_csrf), db: Session = Depends(get_db)):
    lang = _reader(db, user, language)
    _check_kind(kind)
    total, rows = glossary.search(db, lang.code, q[:200], kind, max(1, min(limit, 200)), max(0, offset))
    names = _names(db, [e.updated_by for e in rows])
    return EntryPage(total=total, items=[_out(e, names) for e in rows])


@router.post("/{language}/entries", response_model=EntryOut, status_code=201)
def create_entry(language: str, body: EntryIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lang = _writer(db, user, language, request)
    _check_kind(body.kind)
    if glossary.get_exact(db, lang.code, body.source_text) is not None:
        raise ApiError(409, "duplicate_entry", "That English text is already in this glossary. Edit the existing entry instead.")
    e, _ = glossary.upsert(db, user, lang.code, body.source_text, body.target_text, body.kind, body.notes)
    db.commit()
    audit.record("glossary.entry_created", actor=user, object_type="glossary_entry", object_id=e.id, details={"language": lang.code}, ip=client_ip(request))
    return _out(e, {user.id: user.display_name})


def _entry(db: Session, lang: Language, entry_id: str) -> GlossaryEntry:
    e = db.get(GlossaryEntry, parse_uuid(entry_id, "entry"))
    if e is None or e.language != lang.code:
        raise not_found("entry")
    return e


@router.patch("/{language}/entries/{entry_id}", response_model=EntryOut)
def update_entry(language: str, entry_id: str, body: EntryPatch, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lang = _writer(db, user, language, request)
    e = _entry(db, lang, entry_id)
    _check_kind(body.kind)
    data = body.model_dump(exclude_unset=True)
    if "source_text" in data:
        other = glossary.get_exact(db, lang.code, data["source_text"])
        if other is not None and other.id != e.id:
            raise ApiError(409, "duplicate_entry", "That English text is already in this glossary.")
        e.source_text, e.source_key = data["source_text"].strip(), glossary.key_of(data["source_text"])
    if "target_text" in data:
        e.target_text = data["target_text"].strip()
    if data.get("kind"):
        e.kind = data["kind"]
    if "notes" in data:
        e.notes = (data["notes"] or "").strip() or None
    e.updated_by = user.id
    db.commit()
    db.refresh(e)
    audit.record("glossary.entry_updated", actor=user, object_type="glossary_entry", object_id=e.id, details={"language": lang.code}, ip=client_ip(request))
    return _out(e, {user.id: user.display_name})


@router.delete("/{language}/entries/{entry_id}", status_code=204)
def delete_entry(language: str, entry_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lang = _writer(db, user, language, request)
    e = _entry(db, lang, entry_id)
    db.delete(e)
    db.commit()
    audit.record("glossary.entry_deleted", actor=user, object_type="glossary_entry", object_id=entry_id, details={"language": lang.code}, ip=client_ip(request))
    return Response(status_code=204)


@router.post("/{language}/import", response_model=ImportResult)
async def import_entries(language: str, request: Request, file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """CSV with columns: english, translation, type (optional), notes (optional). Existing English entries are updated."""
    lang = _writer(db, user, language, request)
    data = await file.read(MAX_IMPORT + 1)
    if len(data) > MAX_IMPORT:
        raise ApiError(413, "file_too_large", "That file is too large (2 MB maximum).")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(422, "unreadable_file", "Save the file as UTF-8 CSV and try again.")
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if rows and rows[0] and rows[0][0].strip().lower() in ("english", "source", "source_text", "en"):
        rows = rows[1:]
    if not rows:
        raise ApiError(422, "empty_file", "No rows were found in that file.")
    if len(rows) > MAX_ROWS:
        raise ApiError(422, "too_many_rows", f"Import at most {MAX_ROWS} rows at a time.")
    added = updated = skipped = 0
    errors: List[str] = []
    seen = set()
    for i, r in enumerate(rows, start=1):
        r = [c[1:] if c[:1] == "'" and c[1:2] in ("=", "+", "-", "@") else c for c in r]
        src, tgt = (r[0].strip() if len(r) > 0 else ""), (r[1].strip() if len(r) > 1 else "")
        if not src or not tgt or len(src) > 2000 or len(tgt) > 4000:
            skipped += 1
            if len(errors) < 10:
                errors.append(f"Row {i}: needs both an English text and a translation.")
            continue
        k = glossary.key_of(src)
        if k in seen:
            skipped += 1
            continue
        seen.add(k)
        kind = r[2].strip().lower() if len(r) > 2 else None
        _, created = glossary.upsert(db, user, lang.code, src, tgt, kind if kind in glossary.KINDS else None, r[3] if len(r) > 3 else None)
        added, updated = added + created, updated + (not created)
        db.flush()
    db.commit()
    audit.record("glossary.imported", actor=user, object_type="glossary", object_id=lang.code, details={"added": added, "updated": updated, "skipped": skipped}, ip=client_ip(request))
    return ImportResult(added=added, updated=updated, skipped=skipped, errors=errors)


def _safe(cell: str) -> str:
    return "'" + cell if cell[:1] in ("=", "+", "-", "@") else cell  # keep spreadsheet apps from running formulas


@router.get("/{language}/export")
def export_entries(language: str, user: User = Depends(get_user_no_csrf), db: Session = Depends(get_db)):
    lang = _reader(db, user, language)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["english", "translation", "type", "notes"])
    for e in db.execute(select(GlossaryEntry).where(GlossaryEntry.language == lang.code).order_by(GlossaryEntry.source_text)).scalars():
        w.writerow([_safe(e.source_text), _safe(e.target_text), e.kind, _safe(e.notes or "")])
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="tni-glossary-{lang.code}.csv"'})
