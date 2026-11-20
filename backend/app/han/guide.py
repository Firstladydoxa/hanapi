"""Platform guide: "Han, where can I find the glossary for my language?" answered from the real site map, per role and per translator profile.

Nothing here is generated: every location is a page that exists, and pages a user cannot open are never offered.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import schemas as S
from ..models.db import Language, RhapsodyEdition, User
from ..security.permissions import ADMIN_ROLES
from .rhapsody_chat import Handled

LOCATE_RX = re.compile(
    r"\bwhere\b|\bwhich (page|menu|section|tab)\b|\bhow (do|can|would|should) (i|we) (find|get to|get into|access|reach|open|navigate|go to)\b|"
    r"\b(find|locate|navigate to|take me to|bring me to|show me|lead me to|link to|point me to)\b|\bwhat (page|menu)\b|\bwhere's\b|\bwhere is\b", re.I)
OVERVIEW_RX = re.compile(r"\bwhat (can|could) (i|you|han) do\b|\bwhat (pages|features|sections|modules)\b|\b(site ?map|platform (tour|overview))\b|\bgive me a tour\b|\bwhat is available\b", re.I)


@dataclass(frozen=True)
class Page:
    id: str
    label: str
    path: str
    what: str
    rx: re.Pattern
    admin: bool = False


def _p(i: str, label: str, path: str, what: str, rx: str, admin: bool = False) -> Page:
    return Page(i, label, path, what, re.compile(rx, re.I), admin)


PAGES: List[Page] = [
    _p("chat", "HAN Chat", "/chat", "Ask me about doctrine, terminology, translation and how to use the platform. It is independent of any project.",
       r"\b(chat|talk(ing)? (to|with) (han|you)|conversation|ask han|general questions?)\b"),
    _p("rhapsody", "Rhapsody of Realities", "/rhapsody", "The monthly Rhapsody translation module: activated editions, your translations and the translation editor.",
       r"\brhapsody\b|\bror\b|\bmonthly (translation|edition|devotional)\b|\bdevotional\b"),
    _p("glossary", "Glossary", "/glossary", "The approved TNI glossary of frequently translated words, expressions and sentences.",
       r"\bglossar(y|ies)\b|\bapproved (terms?|words?|expressions?)\b|\bfrequently translated\b"),
    _p("projects", "Projects", "/projects", "Your projects, including the TNI Translator Pilot, with the translation workspace and quick translate inside each one.",
       r"\bprojects?\b|\bpilot\b|\bworkspace\b|\bquick translate\b|\btranslation (editor|history|memory)\b|\bmy translations?\b"),
    _p("languages", "Languages", "/languages", "The languages HAN supports, with their readiness level.",
       r"\blanguages?\b.*\b(list|supported|available|readiness|support)\b|\bsupported languages\b|\blanguage (list|support|readiness)\b"),
    _p("review", "Review languages", "/review", "Language review: where reviewers confirm how well HAN performs in a language.",
       r"\breview (languages?|page|queue)\b|\blanguage review\b|\bproofread(ing)?\b"),
    _p("profile", "Your profile", "/chat", "Your language of expertise is set at registration; if it is missing, a banner at the top of the page lets you choose it.",
       r"\b(my |change |update |set )?(language of )?expertise\b|\bmy (profile|account)\b|\bchange my language\b"),
    _p("users", "Users", "/admin/users", "Create users, change roles (translator, team leader, admin) and deactivate accounts.",
       r"\busers?\b|\broles?\b|\bpromote\b|\baccounts?\b|\bteam leaders?\b", True),
    _p("admin-projects", "Projects & members", "/admin/projects", "Create projects and manage their members.",
       r"\bproject members?\b|\bmembers\b|\bmanage projects?\b|\bcreate (a )?project\b", True),
    _p("terminology", "Terminology", "/admin/terminology", "Approved terminology for projects.", r"\bterminology\b", True),
    _p("knowledge", "Knowledge base", "/admin/knowledge", "The documents HAN learns from: doctrine references, guidelines and platform guides.",
       r"\bknowledge( base)?\b|\bdoctrine (reference|documents?)\b|\bupload (a )?(document|reference)\b", True),
    _p("evidence", "Language evidence", "/admin/evidence", "Evidence used to judge language quality.", r"\bevidence\b", True),
    _p("readiness", "Language readiness", "/admin/readiness", "Language readiness levels.", r"\breadiness\b", True),
]
BY_ID = {p.id: p for p in PAGES}


def _allowed(user: User, page: Page) -> bool:
    return not page.admin or user.role in ADMIN_ROLES or (page.id == "knowledge" and user.role == "team_leader")


def _action(page: Page) -> S.ChatAction:
    return S.ChatAction(type="open_page", path=page.path, label=f"Open {page.label}")


def _language_name(db: Session, user: User) -> Optional[str]:
    lang = db.get(Language, user.expertise_language) if user.expertise_language else None
    return lang.display_name if lang else None


def _open_edition_titles(db: Session) -> List[str]:
    rows = db.execute(select(RhapsodyEdition).where(RhapsodyEdition.status == "active").order_by(RhapsodyEdition.year.desc(), RhapsodyEdition.month.desc())).scalars()
    return [r.title for r in rows]


def _rhapsody(db: Session, user: User) -> Handled:
    page = BY_ID["rhapsody"]
    if user.role in ADMIN_ROLES:
        text = ("Open Rhapsody of Realities from the left menu. Create the monthly edition there, upload the Word manuscript (or attach it with + in chat and ask me to lay it out), "
                "review the master and activate it so translators can start.")
    else:
        titles = _open_edition_titles(db)
        lang = _language_name(db, user)
        text = "Open Rhapsody of Realities from the left menu. "
        text += (f"Editions open for translation now: {', '.join(titles[:3])}. " if titles else "No edition has been activated yet; an administrator has to lay out and activate the next one. ")
        text += (f"The target language is already set to {lang}. Press \"Start / resume translation\", or just tell me \"start my Rhapsody translation\" and I'll open it and draft each paragraph for you."
                 if lang else "Choose your language of expertise first, then start the translation.")
    return Handled(text, [_action(page)])


def _glossary(db: Session, user: User) -> Handled:
    page = BY_ID["glossary"]
    lang = _language_name(db, user)
    if user.role == "translator":
        text = (f"Open Glossary from the left menu. As a translator you'll see the approved {lang} glossary, with search and export." if lang else
                "Open Glossary from the left menu. It shows the glossary of your language of expertise, so choose your language first.")
    else:
        text = "Open Glossary from the left menu and pick the language. Team leaders add and edit the entries for their own language; administrators can see every language."
    return Handled(text, [_action(page)])


def _projects(db: Session, user: User) -> Handled:
    return Handled("Open Projects from the left menu, then open the TNI Translator Pilot project. Inside it you'll find Overview, Quick translate and the Translation workspace. "
                   "My general chat is always available under HAN Chat.", [_action(BY_ID["projects"])])


def _profile(db: Session, user: User) -> Handled:
    lang = _language_name(db, user)
    if lang:
        return Handled(f"Your language of expertise is {lang}; it was chosen at registration and HAN uses it for drafts, the glossary and Rhapsody. If it is wrong, please ask a TNI administrator to change it.")
    return Handled("You haven't chosen a language of expertise yet. A banner at the top of the page lets you pick it; HAN then uses it for drafts, the glossary and Rhapsody.")


SPECIAL = {"rhapsody": _rhapsody, "glossary": _glossary, "projects": _projects, "profile": _profile}


def overview(db: Session, user: User) -> Handled:
    pages = [p for p in PAGES if _allowed(user, p) and p.id != "profile"]
    lines = [f"- {p.label}: {p.what}" for p in pages]
    return Handled("Here is where things are on HAN (all in the left-hand menu):\n\n" + "\n".join(lines) + "\n\nAsk me \"where can I find …\" for any of them.",
                   [_action(p) for p in pages[:3]])


def handle(db: Session, user: User, message: str) -> Optional[Handled]:
    if OVERVIEW_RX.search(message):
        return overview(db, user)
    if not LOCATE_RX.search(message):
        return None
    hits = [p for p in PAGES if p.rx.search(message)]
    if not hits:
        return None
    allowed = [p for p in hits if _allowed(user, p)]
    if not allowed:
        return Handled("That page is only available to TNI administrators. If you need something changed there, please ask an administrator.")
    # the most specific match wins: Rhapsody and glossary before the generic project and chat words
    order = ["rhapsody", "glossary", "profile", "knowledge", "users", "terminology", "admin-projects", "evidence", "readiness", "review", "languages", "projects", "chat"]
    page = sorted(allowed, key=lambda p: order.index(p.id))[0]
    special = SPECIAL.get(page.id)
    if special:
        return special(db, user)
    return Handled(f"Open {page.label} from the left menu. {page.what}", [_action(page)])
