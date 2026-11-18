"""Response-quality guards for model-written replies (spec §3 and §4.3).

A reply that fails a guard is discarded (clean_reply returns None) and the caller uses a deterministic answer instead.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

THINK = re.compile(r"<think>.*?(</think>|$)", re.S | re.I)
GENERIC_OPENER = re.compile(
    r"^\s*(hello|hi|hey|greetings)\b[^.!?\n]{0,40}[.!?]?\s*(how can i (assist|help)[^.!?\n]*[.!?]\s*)?|^\s*how can i (assist|help) you[^.!?\n]*[.!?]\s*", re.I)
VENDOR = re.compile(
    r"\b(qwen|alibaba|openai|chatgpt|gpt-?\d|llama|meta ai|madlad|nllb|afrinllb|ctranslate|google translate|deepl|anthropic|claude|gemini|mistral|"
    r"hugging ?face|gguf|large language model|language model|transformer)\b", re.I)
APPROVAL_CLAIM = re.compile(r"\bi(?:'ve| have| will| am going to)? (?:have )?(?:approved|signed off|finali[sz]ed)\b", re.I)
POLICY_INVENTION = re.compile(r"\b(tni(?:'s)? (?:official )?(?:policy|rule|requirement) (?:is|states|requires)|according to tni policy)\b", re.I)
SENTENCE_END = re.compile(r"[.!?…。」”\"')\]]\s")


def _norm(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


def trim_truncated(text: str) -> str:
    """A reply cut off by the token limit ends at the last complete sentence."""
    t = text.rstrip()
    if not t or t[-1] in ".!?…。\"')”":
        return t
    cut = max((m.end() for m in SENTENCE_END.finditer(t + " ")), default=0)
    return t[:cut].rstrip() if cut > len(t) * 0.4 else t.rstrip(",;: ") + "…"


def clean_reply(text: str, finish_reason: str = "stop", previous: Iterable[str] = (), grounded: bool = False) -> Optional[str]:
    t = THINK.sub("", text or "").strip()
    t = GENERIC_OPENER.sub("", t, count=1).strip()
    if finish_reason == "length":
        t = trim_truncated(t)
    if len(t) < 2:
        return None
    if VENDOR.search(t) or APPROVAL_CLAIM.search(t):
        return None
    if not grounded and POLICY_INVENTION.search(t):
        return None  # TNI policy may only be stated from approved documents
    n = _norm(t)
    for p in list(previous)[-3:]:
        if n and n == _norm(p):
            return None
    words = n.split()
    if len(words) >= 12 and len(set(words)) / len(words) < 0.3:
        return None  # degenerate repetition
    return t[:4000]
