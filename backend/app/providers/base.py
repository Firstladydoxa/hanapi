"""Provider adapter interface. Adapters isolate language codes, prompt formats and errors."""
from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

import httpx

from ..models.internal_schemas import ProviderRequest, ProviderResult

RETRYABLE = {"timeout", "unavailable", "rate_limited"}


class ProviderError(Exception):
    """Normalised provider failure. `category` is internal and never shown to translators."""

    def __init__(self, category: str, message: str = ""):
        super().__init__(f"{category}: {message}")
        self.category = category

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE


class UnsupportedLanguage(ProviderError):
    def __init__(self, code: str):
        super().__init__("unsupported_language", code)


class ProviderAdapter(ABC):
    kind: str = "base"
    external: bool = False  # True when text leaves TNI-controlled infrastructure
    cost_per_char: float = 0.0

    def configured(self) -> bool:
        return True

    @abstractmethod
    def map_language(self, code: str) -> str:
        """HAN code -> provider-native code. Raises UnsupportedLanguage."""

    def supports(self, source_code: str, target_code: str) -> bool:
        try:
            self.map_language(source_code)
            self.map_language(target_code)
            return True
        except UnsupportedLanguage:
            return False

    @abstractmethod
    def _translate(self, req: ProviderRequest) -> Tuple[str, Dict[str, Any]]:
        """Return (translated_text, internal_meta). May raise ProviderError."""

    def translate(self, req: ProviderRequest) -> ProviderResult:
        if not self.configured():
            raise ProviderError("unavailable", "not configured")
        start = time.perf_counter()
        text, meta = self._translate(req)
        latency = int((time.perf_counter() - start) * 1000)
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("malformed", "empty translation")
        if len(text) > max(2000, 20 * len(req.text)):
            raise ProviderError("malformed", "implausible output length")
        chars = len(req.text)
        return ProviderResult(
            text=text.strip(),
            latency_ms=latency,
            billed_chars=chars,
            estimated_cost=round(chars * self.cost_per_char, 6),
            meta=meta,
        )

    def health(self) -> bool:
        return self.configured()


def http_json(
    client: httpx.Client, method: str, url: str, *, json: Any = None, headers: Optional[Dict[str, str]] = None, timeout: float
) -> Any:
    """HTTP call with provider-agnostic error normalisation."""
    try:
        resp = client.request(method, url, json=json, headers=headers, timeout=timeout)
    except httpx.TimeoutException as e:
        raise ProviderError("timeout", type(e).__name__)
    except httpx.TransportError as e:
        raise ProviderError("unavailable", type(e).__name__)
    if resp.status_code == 429:
        raise ProviderError("rate_limited", "429")
    if resp.status_code in (401, 403):
        raise ProviderError("auth", str(resp.status_code))
    if resp.status_code >= 500:
        raise ProviderError("unavailable", str(resp.status_code))
    if resp.status_code >= 400:
        raise ProviderError("bad_request", str(resp.status_code))
    try:
        return resp.json()
    except ValueError:
        raise ProviderError("malformed", "non-JSON response")


_LIST_MARKER = re.compile(r"^\s*[-\u2013\u2014\u2022*]\s+")


def strip_spurious_list_marker(source: str, output: str) -> str:
    """Short inputs sometimes come back as "- Guten Morgen." (a model artefact). Drop the marker unless the source had one."""
    if _LIST_MARKER.match(output) and not _LIST_MARKER.match(source):
        return _LIST_MARKER.sub("", output, count=1)
    return output


class InferenceServiceAdapter(ProviderAdapter):
    """Client for the separate `inference/` model-runtime service (POST /translate)."""

    family = "generic"
    url_setting = ""

    def __init__(self, base_url: Optional[str], token: Optional[str] = None, transport: Optional[httpx.BaseTransport] = None):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token
        self._client = httpx.Client(transport=transport)

    def configured(self) -> bool:
        return bool(self.base_url)

    def build_payload(self, req: ProviderRequest) -> Dict[str, Any]:
        raise NotImplementedError

    def _translate(self, req: ProviderRequest) -> Tuple[str, Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        data = http_json(
            self._client, "POST", f"{self.base_url}/translate", json=self.build_payload(req), headers=headers, timeout=req.timeout_s
        )
        if not isinstance(data, dict) or not isinstance(data.get("translation"), str):
            raise ProviderError("malformed", "missing translation field")
        return strip_spurious_list_marker(req.text, data["translation"]), {"family": self.family}

    def health(self) -> bool:
        if not self.configured():
            return False
        try:
            http_json(self._client, "GET", f"{self.base_url}/health", timeout=3)
            return True
        except ProviderError:
            return False


def degenerate_flag(output: str, source: str):
    """Cheap sanity check on a translation: returns echoes_input / repetition_loop / runaway_length / empty, or None."""
    import zlib

    t = (output or "").strip()
    if not t:
        return "empty"
    if t.casefold() == source.strip().casefold():
        return "echoes_input"
    raw = t.encode()
    if len(raw) > 40 and len(zlib.compress(raw)) / len(raw) < 0.22:
        return "repetition_loop"
    words = t.split()
    if len(words) >= 6 and len(set(words)) / len(words) < 0.25:
        return "repetition_loop"
    if len(t) > 12 * max(len(source), 1):
        return "runaway_length"
    return None
