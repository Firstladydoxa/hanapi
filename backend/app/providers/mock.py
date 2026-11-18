"""Deterministic development/test provider.

Output is `[MOCK DRAFT] <source text>`: it is NOT a translation and is clearly labelled as such.
It can only be built when HAN_ENV != production AND HAN_ENABLE_MOCK_PROVIDER=1 (see
`providers.build_adapter`). In production, when nothing real is configured, the platform
returns `translation_unavailable` instead of fabricating output.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ..models.internal_schemas import ProviderRequest
from .base import ProviderAdapter

MOCK_PREFIX = "[MOCK DRAFT] "


class MockAdapter(ProviderAdapter):
    kind = "mock"
    external = False

    def map_language(self, code: str) -> str:
        return code.lower()

    def _translate(self, req: ProviderRequest) -> Tuple[str, Dict[str, Any]]:
        return MOCK_PREFIX + req.text, {}
