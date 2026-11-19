"""HAN's conversational layer: intent -> grounded or model-written answer, with deterministic fallbacks.

Rules (spec §3-§5): TNI policy only from approved knowledge; terminology only from approved entries (otherwise clearly unverified);
no engine/vendor identity; no approval; short varied replies; a failed or rejected model reply falls back to a deterministic one.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import knowledge
from ..models import schemas as S
from ..models.db import ChatConversation, ChatMessage, Language, LanguageDirection, Project, User
from . import assistant_client, conversations, quality
from . import tools
from .intents import LanguageIndex
from .system_prompt import build_system

INTENTS = [  # order matters: the first match wins
    ("glossary", r"\bglossar(y|ies)\b"),
    ("language_support", r"\b(which|what) languages\b|\bdo you (support|speak|handle)\b|\blanguages? (are )?(available|supported|enabled)\b|"
                         r"\bcan (you|han) translate (to|into|from)\b|\b(is|are) \w+ (supported|available)\b"),
    ("platform_help", r"\b(how (do|can|to|does)|where (do|can|is)|explain how)\b.*\b(han|platform|workspace|quick translate|chat|project|button|panel|history|"
                      r"upload|save|version|translation memory|use)\b|\bwhat can (you|han) do\b|\busing han\b|\bhow to use\b|\bhelp me use\b"),
    ("doctrine", r"\bpastor chris|\boyakhilome\b|\bdoctrin|\brhapsody\b|\bdefinition of\b|\bdefine\b|\b(what is|what's|what are) (the )?(meaning|definition)\b|"
                 r"\b(teach(es|ing|ings)?|says?)\b.*\babout\b"),
    ("terminology", r"\bterminolog|\bglossary\b|\bterm for\b|\b(word|term) for\b|\bhow (do|would) (i|you) (say|translate) (the )?(word|term)\b"),
    ("review", r"\b(review|proofread|check|critique|evaluate)\b.*\b(my|this|the)\b.*\b(translation|draft|text|version)\b|\bis this (translation|draft)\b"),
    ("rewrite", r"\b(more natural|natural(er| expression)|rephrase|reword|rewrite|polish|shorten|simplify|more (formal|informal|polite)|improve (this|my))\b"),
    ("cultural", r"\bcultur|\bidiom|\bproverb|\bfigure of speech|\bexpression\b|\bconnotation|\bhonorific"),
    ("grammar", r"\bgrammar|\btense\b|\bplural|\bconjugat|\bpunctuation|\bspelling|\bgender\b|\bword order\b"),
    ("tni_info", r"\btni\b|\borgani[sz]ation|\bour (policy|policies|guidelines|standards|mission|vision|values)\b|\bstyle guide\b|\bguidelines?\b|"
                 r"\bpolic(y|ies)\b|\bstandards?\b|\bprocedure|\bturnaround|\bdeadline"),
    ("explain", r"\b(explain|difference between|what does .* mean|meaning of|why (is|does|do))\b"),
    ("concept", r"^\W*(han\W+)?(what is|what's|what are|who is|tell me about)\b[^?]{1,60}\??\W*$"),  # a short "what is X?" may be a doctrine term
]
NO_TNI_INFO = [
    "I don't have approved TNI information on that yet, so I won't guess. Please check with a TNI administrator, or ask them to add the document to HAN's knowledge base.",
    "That isn't covered by the approved TNI material I have access to. I'd rather not improvise on TNI policy; a TNI administrator can confirm it.",
]
FALLBACKS = [
    "I can't give a detailed answer right now, but I can still prepare translation drafts, check approved terminology and explain how to use HAN. What would you like to do?",
    "I wasn't able to put a good answer together just now. Try again in a moment, or tell me which text you'd like me to translate.",
    "Sorry, I couldn't answer that properly this time. If you share the text you're working on, I can start with a translation draft.",
]
GREETING_REPLIES = [
    "Hi! Tell me what you're working on: a text to translate, a term to check, or a phrase to polish.",
    "Hello again. What shall we look at next?",
    "I'm here. Paste a text, ask about a term, or ask how something works in HAN.",
    "Ready when you are. What do you need help with?",
]
UNVERIFIED_TERM = "\n\nNote: there is no approved TNI term for this, so please treat any suggestion as unverified and check it with a reviewer."
TERM_FOUND = "The approved terminology for this project has:\n{lines}\n\nPlease use these terms in your translation."
NO_DOCTRINE = [
    "I don't have a reference on file for that in the TNI doctrine material, so I won't improvise a definition. A TNI doctrinal reviewer can confirm it, or the term can be added to the knowledge base.",
    "That term isn't covered in the doctrine reference I have access to. Please check with a TNI doctrinal reviewer rather than rely on a guess from me.",
]
DOCTRINE_RULES = ("Answer ONLY from the TNI SOURCES, which summarise Pastor Chris Oyakhilome's teaching as used by TNI translators. State the meaning as the sources give it, "
                  "mention the Rhapsody of Realities date or title they cite, and add the translation notes that matter. This is the APPROVED TNI doctrine reference, so begin the answer with \"According to the approved TNI doctrine reference:\"."
                  " Do not invent a target-language term; for how to translate it, point to the approved glossary. Do not quote long passages.")
GENERAL_NOTE = {
    "terminology": UNVERIFIED_TERM,
}


@dataclass
class Answer:
    reply: str
    kind: str = "answer"
    sources: List[S.SourceRef] = field(default_factory=list)


def classify(message: str) -> str:
    low = message.lower()
    for name, pattern in INTENTS:
        if re.search(pattern, low, re.S):
            return name
    return "general"


def _pick(options: List[str], conv_messages: int) -> str:
    return options[conv_messages % len(options)]


def _previous_replies(db: Session, conv: ChatConversation) -> List[str]:
    return list(db.execute(select(ChatMessage.content).where(ChatMessage.conversation_id == conv.id, ChatMessage.role != "user")
                           .order_by(ChatMessage.seq.desc()).limit(4)).scalars())


def _count(db: Session, conv: ChatConversation) -> int:
    return len(_previous_replies(db, conv))


def greeting_reply(db: Session, conv: ChatConversation) -> str:
    total = len(db.execute(select(ChatMessage.seq).where(ChatMessage.conversation_id == conv.id)).scalars().all())
    return _pick(GREETING_REPLIES, total)


def _refs(hits) -> List[S.SourceRef]:
    seen, out = set(), []
    for h in hits:
        if h.document_id not in seen:
            seen.add(h.document_id)
            out.append(S.SourceRef(title=h.title, category=h.category, version=h.version))
    return out


def _excerpt(hits) -> str:
    h = hits[0]
    head = f"{h.heading}\n" if h.heading else ""
    return f"This is what the approved material ({h.title}) says:\n\n{head}{h.text[:900]}"


def _segment_context(db: Session, user: User, translation_id: Optional[str]) -> Optional[Dict[str, str]]:
    if not translation_id:
        return None
    from .. import services
    from ..security.permissions import load_segment

    seg, _ = load_segment(db, user, translation_id)  # same access rules as opening the translation itself
    ver = services.latest_version(db, seg.id)
    return {"Source language": seg.source_language, "Target language": seg.target_language, "Source text": seg.source_text[:1500],
            "Current draft": (ver.target_text[:1500] if ver else "")}


def _ask_model(db: Session, conv: ChatConversation, project: Optional[Project], message: str, hits, segment, grounded: bool, extra: str = "") -> Optional[str]:
    history, earlier = conversations.history_for_model(db, conv, message)
    summary = conv.summary
    if earlier:
        summary = (summary + "\n" if summary else "") + "Relevant earlier messages:\n" + earlier
    system = build_system({"name": project.name, "domain": project.domain, "style": project.style, "instructions": (project.instructions or "")[:800]}
                          if project else None, [(h.title + (f" - {h.heading}" if h.heading else ""), h.text) for h in hits], summary, segment)
    if extra:
        system += "\n\n" + extra
    msgs = [{"role": "system", "content": system}] + [m for m in history if m["content"].strip()]
    if not msgs[-1:] or msgs[-1]["role"] != "user" or msgs[-1]["content"][:200] != message[:200]:
        msgs.append({"role": "user", "content": message[:6000]})
    res = assistant_client.chat(msgs)
    if res is None:
        return None
    return quality.clean_reply(res[0], res[1], _previous_replies(db, conv), grounded=grounded)


def language_support_answer(db: Session, user: User, message: str, idx: LanguageIndex) -> Answer:
    from ..languages import availability, language_support

    rows = {r["code"]: r for r in language_support(db)}
    named = []
    for m in re.finditer(r"[A-Za-zÀ-ÿ']+", message):
        code = idx.resolve(m.group(0))
        if code and code in rows and code not in named and code != "en":
            named.append(code)
    labels = {"enabled": "available", "enabled_with_review": "available, with extra review", "controlled_testing": "in controlled testing (drafts are experimental)",
              "not_enabled": "not yet enabled"}
    if named:
        lines = [f"- {rows[c]['name']}: {labels[rows[c]['availability']]}" for c in named[:6]]
        return Answer("Here is where those languages stand:\n" + "\n".join(lines) + "\n\nOpen the Languages page for the full list. A language appearing here "
                      "does not mean its drafts are validated; unvalidated ones are always labelled.", "answer")
    counts: Dict[str, int] = {}
    for r in rows.values():
        counts[r["availability"]] = counts.get(r["availability"], 0) + 1
    return Answer(f"HAN knows {len(rows)} languages. {counts.get('enabled', 0) + counts.get('enabled_with_review', 0)} are available for regular use and "
                  f"{counts.get('controlled_testing', 0)} are in controlled testing (experimental drafts that need careful review); the rest are not enabled yet. "
                  "Ask about a specific language, or open the Languages page for the full list.", "answer")


def terminology_answer(db: Session, user: User, project: Optional[Project], message: str, idx: LanguageIndex, state: Dict, req_langs) -> Optional[Answer]:
    """Approved project terms matching a word in the message, if the language pair is known."""
    if project is None:
        return None
    src, tgt = req_langs
    src, tgt = src or state.get("src"), tgt or state.get("tgt")
    found = [idx.resolve(m.group(0)) for m in re.finditer(r"[A-Za-zÀ-ÿ']+", message)]
    found = [c for c in found if c]
    if not (src and tgt) and len(found) >= 2:
        src, tgt = found[0], found[1]
    elif not tgt and found:
        tgt, src = found[-1], src or "en"
    if not (src and tgt):
        return None
    words = [w for w in re.findall(r"[\w'-]{3,}", message.lower()) if w not in knowledge.STOP]
    lines: List[str] = []
    for w in dict.fromkeys(words):
        for e in tools.search_terminology(db, user, project.id, src, tgt, w)[:2]:
            line = f"- {e.source_term} → {e.target_term}" + (f" ({e.usage_note})" if e.usage_note else "")
            if line not in lines:
                lines.append(line)
    return Answer(TERM_FOUND.format(lines="\n".join(lines[:6]))) if lines else None


def _language_in(message: str, idx: LanguageIndex) -> Optional[str]:
    """A non-English language named in the message, ignoring anything inside quotation marks."""
    bare = re.sub(r"[\"“«].+?[\"”»]", " ", message)
    best = None
    for name in sorted(idx.by_name, key=len, reverse=True):
        m = re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", bare, re.I)
        if m and idx.by_name[name] != "en" and (best is None or m.start() < best[0]):
            best = (m.start(), idx.by_name[name])
    return best[1] if best else None


def _phrase_in(message: str) -> Optional[str]:
    m = re.search(r"[\"“«](.+?)[\"”»]", message, re.S) or re.search(r"(?<![\w])['‘](.+?)['’](?![\w])", message, re.S)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = re.search(r"\b(?:word|term|expression|phrase|sentence|idiom)\s+([^?]+?)(?=\s+(?:is|are|was|has|have|been|be|translated|translate|rendered|said|expressed|written|in|into|to|from|based|according|using|per)\b|[?.!]|$)", message, re.I)
    return m.group(1).strip() if m else None


def glossary_answer(db: Session, message: str, idx: LanguageIndex, state: Dict, req_langs, segment: Optional[Dict[str, str]]) -> Answer:
    from .. import glossary
    from ..models.db import Language

    code = _language_in(message, idx) or req_langs[1] or (req_langs[0] if req_langs[0] not in (None, "en") else None) or state.get("tgt")
    if not code and segment:
        code = idx.resolve(segment.get("Target language"))
    if code == "en":
        code = None
    if not code:
        return Answer("Which language's glossary should I check? Tell me the language, for example: \"in Swahili\".", "clarification")
    lang = db.get(Language, code)
    name = lang.display_name if lang else code
    ref = [S.SourceRef(title=f"TNI glossary: {name}", category="glossary", version=1)]
    phrase = _phrase_in(message)
    text = phrase or (segment or {}).get("Source text") or message
    exact = glossary.get_exact(db, code, phrase) if phrase else None
    if exact:
        note = f"\n\nNote: {exact.notes}" if exact.notes else ""
        return Answer(f"In the approved TNI {name} glossary, \"{exact.source_text}\" is translated as:\n\n{exact.target_text}{note}", "answer", ref)
    found = glossary.find_in_text(db, code, text)
    if found:
        lines = "\n".join(f"- \"{e.source_text}\" → {e.target_text}" + (f" ({e.notes})" if e.notes else "") for e in found[:10])
        lead = (f"The {name} glossary has no entry for the whole of \"{phrase}\", but it does have these parts:" if phrase and len(found) and
                glossary.normalise(found[0].source_text) != glossary.normalise(phrase) else f"From the approved TNI {name} glossary:")
        return Answer(f"{lead}\n{lines}\n\nPlease check them against your sentence; I haven't translated the rest from the glossary.", "answer", ref)
    near = glossary.similar(db, code, phrase) if phrase else []
    if near:
        lines = "\n".join(f"- \"{e.source_text}\" → {e.target_text}" for e in near)
        return Answer(f"The {name} glossary has no entry for \"{phrase}\" itself. These related entries exist:\n{lines}", "answer", ref)
    what = f"\"{phrase}\"" if phrase else "that"
    total, _ = glossary.search(db, code, limit=1)
    if not total:
        return Answer(f"The {name} glossary is empty so far, so I can't give an approved translation for {what}. Your language team leader can add it in the Glossary page.")
    return Answer(f"There is no entry for {what} in the approved TNI {name} glossary, so I won't guess. Ask your language team leader to add it, or check the Glossary page.")


def answer(db: Session, user: User, conv: ChatConversation, project: Optional[Project], message: str, intent: str, idx: LanguageIndex,
           state: Dict, req_langs=(None, None), context_translation_id: Optional[str] = None) -> Answer:
    n = _count(db, conv)
    if intent == "language_support":
        return language_support_answer(db, user, message, idx)

    segment = _segment_context(db, user, context_translation_id)
    pid = project.id if project else None
    if intent == "glossary":
        return glossary_answer(db, message, idx, state, req_langs, segment)
    if intent in ("doctrine", "concept", "explain"):
        hits = knowledge.retrieve(db, user, message, pid, categories=["doctrine"])
        if hits:
            text = _ask_model(db, conv, project, message, hits, segment, True, DOCTRINE_RULES)
            if text:
                lead = "According to the approved TNI doctrine reference:"
                text = text if text.lstrip().lower().startswith("according to the approved") else f"{lead}\n\n{text}"
            return Answer(text or _excerpt(hits), "answer", _refs(hits))
        if intent == "doctrine":
            return Answer(_pick(NO_DOCTRINE, n))
        intent = "general" if intent == "concept" else intent
    if intent == "terminology":
        term = terminology_answer(db, user, project, message, idx, state, req_langs)
        if term:
            return term

    if intent in ("tni_info", "platform_help", "terminology"):
        cats = {"tni_info": ["institutional", "guidelines", "terminology", "language_resources", "faq"],  # the platform guide is never TNI policy
             "platform_help": ["platform", "faq"], "terminology": ["terminology", "guidelines", "language_resources"]}.get(intent)
        hits = knowledge.retrieve(db, user, message, pid, languages=[c for c in req_langs if c], categories=cats)
    else:
        hits = []

    if intent in ("tni_info", "platform_help") and not hits:
        if intent == "platform_help":
            return Answer("I can help with that, but I don't have a guide section matching it. Try the Quick translate and Translation workspace pages, "
                          "or tell me exactly what you're trying to do.")
        return Answer(_pick(NO_TNI_INFO, n))
    if hits:
        text = _ask_model(db, conv, project, message, hits, segment, True,
                          "Answer ONLY from the TNI SOURCES. If they do not answer the question, say so. Do not add facts of your own.")
        return Answer(text or _excerpt(hits), "answer", _refs(hits))

    extra = {
        "terminology": "The translator asks about terminology. No approved TNI term was found. Discuss only terms they mention, describe options as suggestions, and do not call anything an approved or official term.",
        "review": "Review the translator's text constructively: meaning, grammar, tone, fluency. Be specific and short. Do not claim it is correct or approved.",
        "rewrite": "Offer one or two improved wordings, briefly saying why. Keep the original meaning.",
        "cultural": "Explain the cultural or idiomatic point plainly. Say when usage varies by region or when you are unsure.",
    }.get(intent, "")
    text = _ask_model(db, conv, project, message, [], segment, False, extra)
    if text is None:
        return Answer(_pick(FALLBACKS, n))
    return Answer(text + GENERAL_NOTE.get(intent, ""))
