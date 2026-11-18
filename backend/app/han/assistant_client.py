"""Client for the HAN assistant service (chat model + embeddings). Every failure returns None so callers fall back to deterministic replies."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings

log = logging.getLogger("han.assistant")
TRANSPORT: Optional[httpx.BaseTransport] = None  # tests inject a fake transport


def _call(path: str, payload: Dict[str, Any], timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
    s = get_settings()
    if not s.assistant_url:
        return None
    token = os.environ.get("HAN_INFERENCE_TOKEN", "")
    try:
        with httpx.Client(timeout=timeout or s.assistant_timeout_s, transport=TRANSPORT) as c:
            r = c.post(s.assistant_url.rstrip("/") + path, json=payload, headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            log.warning("assistant service returned %s", r.status_code)
            return None
        return r.json()
    except Exception:  # noqa: BLE001 - never surface transport details
        log.warning("assistant service unreachable")
        return None


def chat(messages: List[Dict[str, str]]) -> Optional[tuple[str, str]]:
    """Returns (text, finish_reason) or None when the assistant is unavailable."""
    s = get_settings()
    out = _call("/chat", {"messages": messages, "max_tokens": s.chat_max_tokens, "temperature": s.chat_temperature})
    if not out or not isinstance(out.get("text"), str):
        return None
    return out["text"], str(out.get("finish_reason") or "stop")


def embed(texts: List[str], kind: str = "passage") -> Optional[List[List[float]]]:
    out = _call("/embed", {"texts": texts, "kind": kind}, timeout=60)
    vecs = out.get("embeddings") if out else None
    return vecs if isinstance(vecs, list) and len(vecs) == len(texts) else None
