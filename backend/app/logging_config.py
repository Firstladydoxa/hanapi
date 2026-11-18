"""Structured logging with request correlation IDs. Never logs translation text by default."""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import sys
from typing import Any, Dict

from .config import get_settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in _RESERVED and k != "request_id" and not k.startswith("_"):
                data[k] = v
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging() -> None:
    s = get_settings()
    root = logging.getLogger()
    root.setLevel(s.log_level.upper())
    for h in list(root.handlers):
        if getattr(h, "_han", False):
            root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler._han = True  # type: ignore[attr-defined]
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter() if s.log_json else logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)


def fingerprint(text: str) -> Dict[str, Any]:
    """Loggable description of user content: length + short hash (full text only if content logging is on)."""
    d: Dict[str, Any] = {"len": len(text or ""), "sha256": hashlib.sha256((text or "").encode()).hexdigest()[:12]}
    if get_settings().content_logging:
        d["text"] = text
    return d


def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()
