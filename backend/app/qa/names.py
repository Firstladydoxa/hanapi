"""Proper-name preservation (heuristic: capitalised, non-sentence-initial tokens in Latin-script text)."""
from __future__ import annotations

import re
from typing import List

from . import NON_LATIN_SCRIPTS, QAContext, warn

TOKEN = re.compile(r"(?<![\w])([^\W\d_][\w'\u2019-]*)")
CAPITALISES_NOUNS = {"de", "lb"}  # German capitalises all nouns: the heuristic would be noise
# Capitalised words that are translated rather than preserved (months, weekdays, the pronoun "I").
TRANSLATED_WORDS = {
    "i", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
}


def _sentence_initial(text: str, pos: int) -> bool:
    before = text[:pos].rstrip(" \t\"'\u201c\u00ab([")
    return not before or before[-1] in ".!?\n:;"


def check(ctx: QAContext) -> List[dict]:
    if ctx.source_language in CAPITALISES_NOUNS or ctx.target_script in NON_LATIN_SCRIPTS:
        return []
    missing: List[str] = []
    for m in TOKEN.finditer(ctx.source_text):
        tok = m.group(1)
        if not tok[0].isupper() or len(tok) < 2 or tok.lower() in TRANSLATED_WORDS or _sentence_initial(ctx.source_text, m.start()):
            continue
        if tok not in ctx.target_text and tok not in missing:
            missing.append(tok)
    if not missing:
        return []
    return [warn("name", "Please check how these names were handled in the translation: " + ", ".join(missing[:8]) + ".",
                 severity="info")]
