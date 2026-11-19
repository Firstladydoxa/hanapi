"""HAN chat commands for the Rhapsody of Realities workflow.

Administrators: "Han, start the layout of Rhapsody for the month of November 2026 using the word document I uploaded".
Translators:    "Han, start the translation of Rhapsody in French for the month of November".
HAN only does what the signed-in user is allowed to do on the dashboard, and never activates a master or approves a translation itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import rhapsody_draft as drafting
from .. import rhapsody_layout as layout
from ..errors import ApiError
from ..models import schemas as S
from ..models.db import RhapsodyEdition, RhapsodySourceFile, User
from ..security.permissions import ADMIN_ROLES
from .intents import LanguageIndex

MONTH_RX = re.compile(r"\b(" + "|".join(m.lower() for m in layout.MONTHS) + r")\b(?:\s*,?\s*(\d{4}))?", re.I)
LAYOUT_RX = re.compile(r"\brhapsody\b.*\blay-?out\b|\blay-?out\b.*\brhapsody\b", re.I | re.S)
TRANSLATE_RX = re.compile(r"\b(start|begin|open|resume|continue|do|prepare)\b.*\btranslat(e|ion|ing)\b.*\brhapsody\b|\b(start|begin|open|resume|continue)\b.*\brhapsody\b.*\btranslat", re.I | re.S)


@dataclass
class Handled:
    text: str
    actions: List[S.ChatAction] = field(default_factory=list)


def _period(message: str) -> Tuple[Optional[int], Optional[int]]:
    m = MONTH_RX.search(message)
    if not m:
        return None, None
    return [x.lower() for x in layout.MONTHS].index(m.group(1).lower()) + 1, int(m.group(2)) if m.group(2) else None


def _language(message: str, idx: LanguageIndex) -> Optional[str]:
    bare = re.sub(r"\b(" + "|".join(m.lower() for m in layout.MONTHS) + r")\b", " ", message, flags=re.I)
    best = None
    for name in sorted(idx.by_name, key=len, reverse=True):
        m = re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", bare, re.I)
        if m and idx.by_name[name] != "en" and (best is None or m.start() < best[0]):
            best = (m.start(), idx.by_name[name])
    return best[1] if best else None


def handle(db: Session, user: User, message: str, idx: LanguageIndex) -> Optional[Handled]:
    if not re.search(r"\brhapsody\b", message, re.I):
        return None
    try:
        if LAYOUT_RX.search(message):
            return _layout(db, user, message)
        if TRANSLATE_RX.search(message):
            return _translation(db, user, message, idx)
    except ApiError as e:
        db.rollback()
        return Handled(e.message)
    return None


def _layout(db: Session, user: User, message: str) -> Handled:
    from ..api import rhapsody as api

    if user.role not in ADMIN_ROLES:
        return Handled("Only a TNI administrator can prepare the Rhapsody layout. Please ask an administrator, or open Rhapsody to see the editions that are already available.")
    month, year = _period(message)
    if not month:
        return Handled("Which month should I lay out? For example: \"start the layout of Rhapsody for November 2026\".")
    year = year or datetime.now().year
    edition = db.execute(select(RhapsodyEdition).where(RhapsodyEdition.year == year, RhapsodyEdition.month == month)).scalar_one_or_none()
    label = f"{layout.MONTHS[month - 1]} {year}"
    if edition is None:
        return Handled(f"There is no Rhapsody edition for {label} yet, and I can't see an uploaded Word document for it. In Rhapsody, create the {label} edition and upload the Word manuscript, then ask me again.")
    sources = list(db.execute(select(RhapsodySourceFile).where(RhapsodySourceFile.edition_id == edition.id).order_by(RhapsodySourceFile.created_at.desc())).scalars())
    docx = next((s for s in sources if s.format == "docx"), None)
    if docx is None:
        return Handled(f"The {label} edition has no Word document yet. Upload the manuscript on the edition page, then ask me again.")
    template = next((s for s in sources if s.format == "xliff"), None)
    result = api.ingest_edition(db, edition, docx, template, user)
    v = result["validation"]
    lines = [f"I've laid out Rhapsody for {label} from \"{docx.filename}\": {v.get('articles', 0)} of {v.get('expected_articles', 0)} articles recognised, "
             f"{v['segment_count']} translatable paragraphs in {v['section_count']} sections (master version {result['version_number']})."]
    if v["warnings"]:
        lines.append("Please check:\n" + "\n".join(f"- {w}" for w in v["warnings"][:8]) + (f"\n- and {len(v['warnings']) - 8} more" if len(v["warnings"]) > 8 else ""))
    if v["blocking_errors"]:
        lines.append("This master cannot be activated yet:\n" + "\n".join(f"- {w}" for w in v["blocking_errors"]))
    else:
        lines.append("Review the master and activate it when it is right. Once it is active, translators can start translating it.")
    return Handled("\n\n".join(lines), [S.ChatAction(type="open_rhapsody", path=f"/rhapsody/editions/{edition.id}", label="Review the master")])


def _translation(db: Session, user: User, message: str, idx: LanguageIndex) -> Handled:
    from ..api import rhapsody as api

    if user.role not in {"translator", *ADMIN_ROLES}:
        return Handled("Rhapsody translation is started by translators. Open Rhapsody to see the editions.")
    lang = _language(message, idx)
    if not lang:
        return Handled("Which language should I translate Rhapsody into? For example: \"start the translation of Rhapsody in French for November\".")
    month, year = _period(message)
    stmt = select(RhapsodyEdition).where(RhapsodyEdition.status == "active").order_by(RhapsodyEdition.year.desc(), RhapsodyEdition.month.desc())
    if month:
        stmt = stmt.where(RhapsodyEdition.month == month)
    if year:
        stmt = stmt.where(RhapsodyEdition.year == year)
    edition = db.execute(stmt).scalars().first()
    if edition is None:
        when = f"for {layout.MONTHS[month - 1]}{f' {year}' if year else ''}" if month else ""
        return Handled(f"No activated English master is available {when}yet. An administrator has to lay out and activate the edition first.".replace("  ", " "))
    row, created = api.start_for_translator(db, user, edition, lang)
    drafted = False
    if row.draft_status in {"idle", "failed"}:
        drafted = drafting.start_drafting(db, row, user)
        db.refresh(row)
    lang_name = next((n for n, c in idx.by_name.items() if c == lang), lang).title()
    text = (f"I've opened the {edition.title} English master for {lang_name}. " if created else f"Your {lang_name} translation of {edition.title} is already open. ")
    if drafted or row.draft_status == "running":
        text += ("I'm drafting a suggestion for each paragraph in the right-hand column, using the TNI glossary and terminology. You'll see them appear as I go. "
                 "Review them paragraph by paragraph and correct what needs it; nothing is final until you submit.")
    elif row.draft_status == "done":
        text += "My drafts are ready; continue reviewing them paragraph by paragraph."
    else:
        text += "Open it to continue."
    return Handled(text, [S.ChatAction(type="open_rhapsody", path=f"/rhapsody/translate/{row.id}", label="Open the translation")])
