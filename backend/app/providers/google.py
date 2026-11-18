"""Google Cloud Translation (Basic / v2) REST adapter. EXTERNAL provider: text leaves TNI infrastructure.

Only used for projects with `allow_external_processing=true`. HTTPS only; the API key is sent in a
header (never in the URL, so it cannot leak through access logs).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import httpx

from ..models.internal_schemas import ProviderRequest
from .base import ProviderAdapter, ProviderError, UnsupportedLanguage, http_json
from .language_codes import GOOGLE_EXCEPTIONS

COST_PER_CHAR = 20.0 / 1_000_000  # list price at time of writing; recheck before budgeting


class GoogleAdapter(ProviderAdapter):
    kind = "google"
    external = True
    cost_per_char = COST_PER_CHAR

    def __init__(self, api_key: Optional[str], base_url: str, transport: Optional[httpx.BaseTransport] = None):
        if not base_url.lower().startswith("https://"):
            raise ValueError("Google adapter requires an https:// endpoint")
        self.api_key = api_key
        self.base_url = base_url
        self._client = httpx.Client(transport=transport)

    def configured(self) -> bool:
        return bool(self.api_key)

    def map_language(self, code: str) -> str:
        c = code.lower()
        if not c:
            raise UnsupportedLanguage(code)
        return GOOGLE_EXCEPTIONS.get(c, c)

    def _translate(self, req: ProviderRequest) -> Tuple[str, Dict[str, Any]]:
        body = {
            "q": req.text,
            "source": self.map_language(req.source_code),
            "target": self.map_language(req.target_code),
            "format": "text",
        }
        data = http_json(
            self._client,
            "POST",
            self.base_url,
            json=body,
            headers={"X-Goog-Api-Key": self.api_key or ""},
            timeout=req.timeout_s,
        )
        try:
            return data["data"]["translations"][0]["translatedText"], {}
        except (KeyError, IndexError, TypeError):
            raise ProviderError("malformed", "unexpected response shape")
