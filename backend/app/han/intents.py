"""Deterministic, rule-based intent parsing for HAN chat (no external language model)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

ENGINE_WORDS = re.compile(
    r"\b(engine|model|provider|vendor|chatgpt|gpt|openai|google translate|deepl|llm|which ai|what ai|powered by|routing|"
    r"under the hood|api you use|nllb|madlad)\b", re.I)
ENGINE_QUESTION = re.compile(r"\b(which|what|who|how|are you|do you|did you|is this|was this|used|using)\b", re.I)
APPROVE_WORDS = re.compile(r"\b(approve|approved|approval|sign[- ]off|finali[sz]e|mark (it|this) as (done|final))\b", re.I)
TRANSLATE_REQUEST = re.compile(r"^\s*(please\s+|can you\s+|could you\s+)?translate\b", re.I)
TRANSLATE_ACTION = re.compile(r"\b(translate|render|put into|convert)\b", re.I)
GREETING = re.compile(r"^\s*(hi|hello|hey|good (morning|afternoon|evening)|help|what can you do)\b[\s!.?]*$", re.I)
TRANSLATE_VERB = re.compile(r"\b(translate|translation|render|put into|convert)\b", re.I)
QUOTES = re.compile(r"[\"“«](.+?)[\"”»]", re.S)

# Common alias names that are not the registered display name.
ALIASES = {"chinese": "zh", "mandarin": "zh", "farsi": "fa", "brazilian portuguese": "pt", "castilian": "es", "swahili": "sw",
           "kiswahili": "sw", "filipino": "fil", "tagalog": "tl"}


@dataclass
class Parsed:
    kind: str  # engine | approve | greeting | translate | language_only | text_only | other
    text: Optional[str] = None
    source: Optional[str] = None
    target: Optional[str] = None
    unknown_language: bool = False


class LanguageIndex:
    def __init__(self, languages: Dict[str, str]):
        """languages: code -> display name (as stored)."""
        self.by_name: Dict[str, str] = {}
        for code, name in languages.items():
            self.by_name[name.lower()] = code
            base = re.sub(r"\s*\(.*?\)\s*", "", name).strip().lower()
            self.by_name.setdefault(base, code)
        for alias, code in ALIASES.items():
            if code in languages:
                self.by_name.setdefault(alias, code)
        self.codes = set(languages)
        names = sorted(self.by_name, key=len, reverse=True)
        self.name_alt = "|".join(re.escape(n) for n in names) or r"(?!x)x"

    def resolve(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        t = token.strip().strip(".,:;!?\"'“”").lower()
        if t in self.by_name:
            return self.by_name[t]
        t2 = t.replace("_", "-")
        return t2 if t2 in self.codes else None

    @property
    def lang_pattern(self) -> str:
        return rf"(?:{self.name_alt}|[a-z]{{2,3}}(?:-[a-z0-9]{{2,8}})?)"


def _split(message: str) -> Tuple[str, Optional[str]]:
    """(instruction, text). Text comes from quotes, after a colon, or after a newline."""
    m = QUOTES.search(message)
    if m:
        return (message[: m.start()] + " " + message[m.end():]).strip(), m.group(1).strip()
    if ":" in message:
        head, tail = message.split(":", 1)
        if len(head) <= 160 and tail.strip():
            return head.strip(), tail.strip()
    if "\n" in message.strip():
        head, tail = message.strip().split("\n", 1)
        if tail.strip():
            return head.strip(), tail.strip()
    return message.strip(), None


def parse(message: str, idx: LanguageIndex) -> Parsed:
    msg = message.strip()
    if ENGINE_WORDS.search(msg) and ENGINE_QUESTION.search(msg) and not TRANSLATE_REQUEST.match(msg):
        return Parsed("engine")
    if APPROVE_WORDS.search(msg) and len(msg) < 200 and not TRANSLATE_ACTION.search(msg):
        return Parsed("approve")
    if GREETING.match(msg):
        return Parsed("greeting")

    L = idx.lang_pattern
    instruction, text = _split(msg)
    low = instruction.lower()
    src = tgt = None
    unknown = False

    m = re.search(rf"\b(?P<s>{L})\s*(?:->|→|=>|\bto\b|\binto\b)\s*(?P<t>{L})\b\s*$", low)
    if m and not re.search(r"\bfrom\b", low):
        src, tgt = idx.resolve(m.group("s")), idx.resolve(m.group("t"))
    m = re.search(rf"\bfrom\s+(?P<s>{L})\b", low)
    if m:
        src = idx.resolve(m.group("s")) or src
    m = re.search(rf"\b(?:to|into|in)\s+(?P<t>{L})\b(?!\s+(?:the|a|an)\b)", low)
    if m and not tgt:
        tgt = idx.resolve(m.group("t"))
    # "translate <text> to <lang>" with inline text and no quotes/colon
    if text is None:
        m = re.match(rf"^\s*translate\s+(?P<text>.+?)\s+(?:from\s+(?P<s>{L})\s+)?(?:to|into)\s+(?P<t>{L})\s*[.!?]*\s*$", msg, re.I | re.S)
        if m and idx.resolve(m.group("t")):
            text = m.group("text").strip().strip("\"“”")
            src = idx.resolve(m.group("s")) or src
            tgt = idx.resolve(m.group("t"))
            # "translate this text/the following to X" without actual content -> no text yet
            if re.fullmatch(r"(this|that|the following|the text|this text|the following text|it)", text.lower()):
                text = None
    if (re.search(r"\b(from|to|into)\s+\w+", low)) and not (src or tgt) and TRANSLATE_VERB.search(low):
        unknown = True

    if TRANSLATE_VERB.search(low) or (src and tgt and text):
        return Parsed("translate", text=text, source=src, target=tgt, unknown_language=unknown)
    lang_only = idx.resolve(msg)
    if lang_only:
        return Parsed("language_only", target=lang_only)
    return Parsed("text_only", text=msg)
