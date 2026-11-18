"""Adapter factory. Adapters are built lazily from settings; unknown/unconfigured kinds yield None."""
from __future__ import annotations

from typing import Dict, Optional

from ..config import Settings, get_settings
from .base import ProviderAdapter

_cache: Dict[str, ProviderAdapter] = {}


def build_adapter(kind: str, settings: Optional[Settings] = None) -> Optional[ProviderAdapter]:
    s = settings or get_settings()
    if kind == "mock":
        if not s.mock_provider_allowed:
            return None
        from .mock import MockAdapter

        return MockAdapter()
    if kind == "google":
        if not s.google_api_key:
            return None
        from .google import GoogleAdapter

        return GoogleAdapter(s.google_api_key, s.google_base_url)
    if kind in ("madlad", "afrinllb", "nllb"):
        url = {"madlad": s.madlad_url, "afrinllb": s.afrinllb_url, "nllb": s.nllb_url}[kind]
        if not url:
            return None
        if kind == "madlad":
            from .madlad import MadladAdapter as cls
        elif kind == "afrinllb":
            from .afrinllb import AfriNLLBAdapter as cls
        else:
            from .nllb import NLLBAdapter as cls
        return cls(url, s.inference_token)
    return None


def get_adapter(kind: str) -> Optional[ProviderAdapter]:
    if kind not in _cache:
        adapter = build_adapter(kind)
        if adapter is None:
            return None
        _cache[kind] = adapter
    return _cache[kind]


def clear_adapter_cache() -> None:
    _cache.clear()
