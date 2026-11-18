"""Formatting: tags, placeholders, whitespace, terminal punctuation and gross length anomalies."""
from __future__ import annotations

import re
from collections import Counter
from typing import List

from . import QAContext, warn

TAG = re.compile(r"</?[A-Za-z][^<>]*?/?>")
PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}|\{[A-Za-z0-9_.]*\}|%\([A-Za-z0-9_]+\)[sdif]|%[sdif]|\$\{[^{}]+\}")
TERMINAL = ".!?:;\u2026\u3002\uff01\uff1f\u061f\u0964\u06d4\u1362"


def check(ctx: QAContext) -> List[dict]:
    out: List[dict] = []
    s, t = ctx.source_text, ctx.target_text

    for label, rx in (("tags", TAG), ("placeholders", PLACEHOLDER)):
        a, b = Counter(rx.findall(s)), Counter(rx.findall(t))
        if a != b:
            diff = sorted(((a - b) + (b - a)).keys())
            out.append(warn("format", f"The {label} in the translation do not match the source: " + ", ".join(diff[:6])
                            + ". Please make sure they are preserved exactly."))

    if s[:1].isspace() != t[:1].isspace() or s[-1:].isspace() != t[-1:].isspace():
        out.append(warn("format", "Leading or trailing spaces differ between the source and the translation.", severity="info"))
    if "  " in t and "  " not in s:
        out.append(warn("format", "The translation contains double spaces.", severity="info"))

    s_end, t_end = s.rstrip()[-1:], t.rstrip()[-1:]
    if s_end and t_end and (s_end in TERMINAL) != (t_end in TERMINAL):
        out.append(warn("format", "The ending punctuation of the translation differs from the source. Please check it.", severity="info"))

    ls, lt = len(s.strip()), len(t.strip())
    if ls >= 20 and (lt == 0 or lt > 4 * ls or lt < ls / 5):
        out.append(warn("format", "The translation is much shorter or longer than the source, which can indicate an omission or "
                        "addition. Please check it."))
    return out
