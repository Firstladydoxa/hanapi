"""AfriNLLB (African-language specialist) via the inference service; FLORES-200 codes."""
from __future__ import annotations

from typing import Any, Dict

from ..models.internal_schemas import ProviderRequest
from .base import InferenceServiceAdapter, UnsupportedLanguage
from .language_codes import AFRINLLB_CODES, flores


class AfriNLLBAdapter(InferenceServiceAdapter):
    kind = "afrinllb"
    family = "afrinllb"
    external = False

    def map_language(self, code: str) -> str:
        c = code.lower()
        mapped = flores(c) if c in AFRINLLB_CODES else None
        if not mapped:
            raise UnsupportedLanguage(code)
        return mapped

    def build_payload(self, req: ProviderRequest) -> Dict[str, Any]:
        return {
            "family": self.family,
            "text": req.text,
            "source_lang": self.map_language(req.source_code),
            "target_lang": self.map_language(req.target_code),
        }
