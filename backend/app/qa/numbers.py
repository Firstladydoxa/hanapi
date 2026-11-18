"""Number preservation check (digits, separators, non-ASCII digit systems)."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import List

from . import QAContext, warn

NUM_RE = re.compile(r"\d+(?:[.,\u00a0\u202f' ]\d{3})*(?:[.,]\d+)?")


def _canon(token: str) -> str:
    digits = []
    for ch in token:
        if ch.isdigit():
            digits.append(str(unicodedata.decimal(ch, 0)) if not ch.isascii() else ch)
    return "".join(digits).lstrip("0") or "0"


def extract_numbers(text: str) -> Counter:
    c: Counter = Counter()
    for m in NUM_RE.finditer(text):
        c[_canon(m.group(0))] += 1
    return c


def check(ctx: QAContext) -> List[dict]:
    src, tgt = extract_numbers(ctx.source_text), extract_numbers(ctx.target_text)
    out: List[dict] = []
    missing = sorted((src - tgt).keys())
    extra = sorted((tgt - src).keys())
    if missing:
        out.append(warn("number", "These numbers appear in the source but may be missing or changed in the translation: "
                        + ", ".join(missing[:8]) + ". Please check them."))
    if extra:
        out.append(warn("number", "These numbers appear in the translation but not in the source: "
                        + ", ".join(extra[:8]) + ". Please check them."))
    return out
