"""INTERNAL provider / routing schemas.

SECURITY: this module must never be imported by public serializers or translator-facing
schemas (`schemas.py`, `security/serializers.py`). A test enforces that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProviderRequest:
    text: str
    source_code: str
    target_code: str
    context: Optional[str] = None
    domain: Optional[str] = None
    glossary: List[Dict[str, str]] = field(default_factory=list)
    request_id: Optional[str] = None
    timeout_s: float = 20.0


@dataclass
class ProviderResult:
    """Normalised provider response (all adapters must return exactly this)."""

    text: str
    latency_ms: int
    billed_chars: int
    estimated_cost: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Candidate:
    model_key: str
    provider: str
    score: float
    reason: str
    model: Any  # ModelRegistry row (detached)
    adapter: Any


@dataclass
class Rejection:
    model_key: str
    reason: str


@dataclass
class RoutePlan:
    candidates: List[Candidate]
    rejections: List[Rejection]
    tier: str


@dataclass
class GatewayResult:
    text: str
    model_key: str
    attempts: int
    fallback_used: bool
    latency_ms: int
    estimated_cost: float
    routing_event_ids: List[Any]
