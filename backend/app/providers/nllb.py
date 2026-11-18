"""NLLB-200 via the inference service (FLORES-200 codes).

LICENCE: the public NLLB-200 weights are CC-BY-NC-4.0 (research/evaluation only). The
registry row for this adapter ships with `license_cleared=false`, and the router refuses to
route to any model without cleared licence evidence.
"""
from __future__ import annotations

from typing import Any, Dict

from ..models.internal_schemas import ProviderRequest
from .base import InferenceServiceAdapter, UnsupportedLanguage
from .language_codes import flores


class NLLBAdapter(InferenceServiceAdapter):
    kind = "nllb"
    family = "nllb"
    external = False

    def map_language(self, code: str) -> str:
        mapped = flores(code)
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
