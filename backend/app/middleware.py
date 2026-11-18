"""ASGI middleware: correlation IDs, security headers, body-size cap and the engine-confidentiality safety net."""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Iterable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import get_settings
from .database import SessionLocal
from .errors import GENERIC_ERROR_MESSAGE, error_body
from .logging_config import request_id_var
from .models.registry import DENYLIST_KEYS, DENYLIST_WORDS, registry_identifiers

log = logging.getLogger("han.middleware")

_REQ_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

# Admin endpoints that legitimately carry engine details (they are role-gated by the backend).
ENGINE_PATH_PREFIXES = (
    "/v1/admin/models",
    "/v1/admin/routing-events",
    "/v1/admin/usage",
    "/v1/admin/health",
)

# Free-text content fields: user content may legitimately mention any word, so they are not scanned.
CONTENT_KEYS = {
    "translated_text", "source_text", "target_text", "text", "context", "reply", "message", "definition", "usage_note",
    "comment", "change_note", "title", "question", "instructions", "review_note", "source_term", "target_term", "display_name",
    "name", "client", "email", "style", "domain", "forbidden", "note", "span", "changes", "from", "to",
}
_TOKEN = re.compile(r"[a-z0-9][a-z0-9._/-]*")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQ_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > get_settings().max_body_bytes:
                resp: Response = JSONResponse(error_body("payload_too_large", "The submitted content is too large."), status_code=413)
            else:
                resp = await call_next(request)
        finally:
            request_id_var.reset(token)
        resp.headers["X-Request-ID"] = rid
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp


def _walk(obj: Any, registry_ids: Iterable[str], under_content: bool = False) -> Optional[str]:
    """Return a description of the first violation found (structure only, never user content)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in DENYLIST_KEYS:
                return f"key:{lk}"
            if lk in DENYLIST_WORDS:
                return f"key:{lk}"
            bad = _walk(v, registry_ids, under_content or lk in CONTENT_KEYS)
            if bad:
                return bad
    elif isinstance(obj, list):
        for v in obj:
            bad = _walk(v, registry_ids, under_content)
            if bad:
                return bad
    elif isinstance(obj, str) and not under_content:
        low = obj.lower()
        if len(low) <= 200:
            tokens = set(_TOKEN.findall(low))
            for ident in registry_ids:
                if ident in tokens or low == ident:
                    return "value:registry-identifier"
            if tokens & DENYLIST_WORDS:
                return "value:denylisted-word"
    return None


class EngineConfidentialityMiddleware(BaseHTTPMiddleware):
    """Fail-closed safety net. Whitelist serialisation (security/serializers.py) is the primary control."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if not path.startswith("/v1/") or path.startswith(ENGINE_PATH_PREFIXES):
            return response
        if "application/json" not in response.headers.get("content-type", ""):
            return response
        body = b""
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            body += chunk
        headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")}
        try:
            data = json.loads(body) if body else None
        except ValueError:
            data = None
        violation = None
        if data is not None:
            with SessionLocal() as db:
                violation = _walk(data, registry_identifiers(db))
        for hname in response.headers.keys():
            if hname.lower() in {"x-model", "x-provider", "x-route", "x-latency-ms", "server-timing"}:
                violation = violation or f"header:{hname.lower()}"
        if violation:
            log.error("engine_confidentiality_violation_blocked", extra={"where": violation, "path": path})
            return JSONResponse(error_body("internal_error", GENERIC_ERROR_MESSAGE), status_code=500, headers={
                k: v for k, v in headers.items() if k.lower() == "x-request-id"})
        return Response(content=body, status_code=response.status_code, headers=headers, media_type="application/json")
