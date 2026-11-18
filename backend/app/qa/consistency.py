"""Consistency: repeated source sentences, repeated words, and prior approved translations."""
from __future__ import annotations

import re
from typing import List

from . import QAContext, warn

SENT_SPLIT = re.compile(r"(?<=[.!?\u3002\uff01\uff1f\u061f\u0964])\s+|\n+")
DOUBLE_WORD = re.compile(r"\b(\w{2,})\s+\1\b", re.IGNORECASE)


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in SENT_SPLIT.split(text) if s and s.strip()]


def check(ctx: QAContext) -> List[dict]:
    out: List[dict] = []
    src, tgt = _sentences(ctx.source_text), _sentences(ctx.target_text)
    if len(src) == len(tgt) and len(src) > 1:
        seen: dict = {}
        for s, t in zip(src, tgt):
            key = s.casefold()
            if key in seen and seen[key] != t:
                out.append(warn("consistency", f"The repeated sentence \u201c{s[:60]}\u201d has been translated in different ways. "
                                "Please check that the wording is consistent."))
                break
            seen.setdefault(key, t)
    m = DOUBLE_WORD.search(ctx.target_text)
    if m and not ctx.source_text.lower().count(m.group(0).lower()):
        out.append(warn("consistency", f"The word \u201c{m.group(1)}\u201d appears twice in a row in the translation. Is that intended?",
                        severity="info"))
    for tm in ctx.prior_translations:
        if tm.target_text.strip() != ctx.target_text.strip():
            out.append(warn("consistency", "This source text was previously approved in this project with a different translation. "
                            "Please check whether the earlier wording should be reused.", severity="info"))
            break
    return out
