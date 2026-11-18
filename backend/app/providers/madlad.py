"""MADLAD-400 via the inference service. Target language is selected with a `<2xx>` prefix."""
from __future__ import annotations

from typing import Any, Dict

from ..models.internal_schemas import ProviderRequest
from .base import InferenceServiceAdapter, UnsupportedLanguage
from .language_codes import madlad_token


class MadladAdapter(InferenceServiceAdapter):
    kind = "madlad"
    family = "madlad"
    external = False

    def map_language(self, code: str) -> str:
        token = madlad_token(code)
        if token is None:
            raise UnsupportedLanguage(code)
        return token

    def build_payload(self, req: ProviderRequest) -> Dict[str, Any]:
        self.map_language(req.source_code)  # source is not sent, but must be a supported language
        target = self.map_language(req.target_code)
        return {"family": self.family, "text": f"<2{target}> {req.text}", "target_lang": target}
