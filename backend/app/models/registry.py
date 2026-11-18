"""Model registry service (INTERNAL). Registry rows hold provider/model identity and licence evidence."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..providers import get_adapter
from ..providers.base import ProviderAdapter
from .db import ModelRegistry

# Tests may inject fake adapters keyed by model key.
ADAPTER_OVERRIDES: Dict[str, ProviderAdapter] = {}

DEFAULT_MODELS: List[Dict[str, Any]] = [
    dict(key="madlad-400-3b-mt", provider="madlad", model_name="google/madlad400-3b-mt", license="Apache-2.0 (verify)",
         runtime="local inference service (CTranslate2/Transformers)", max_chars=4000, avg_latency_ms=2500, priority=10),
    dict(key="madlad-400-7b-mt", provider="madlad", model_name="google/madlad400-7b-mt", license="Apache-2.0 (verify)",
         runtime="local inference service (GPU recommended)", max_chars=4000, avg_latency_ms=4000, priority=20),
    dict(key="afrinllb-514m-iterative", provider="afrinllb", model_name="AfriNLP/AfriNLLB-12enc-6dec-iterative-514m-ft",
         license="CC-BY-NC-4.0 (per model card; re-verify)", runtime="local inference service", max_chars=3000, avg_latency_ms=1200,
         priority=10, notes="Non-commercial licence on the model card: evaluation only. Do NOT set license_cleared without written legal clearance."),
    dict(key="afrinllb-600m-full", provider="afrinllb", model_name="AfriNLP/AfriNLLB-12enc-12dec-full-ft",
         license="CC-BY-NC-4.0 (per model card; re-verify)", runtime="local inference service", max_chars=3000, avg_latency_ms=1800,
         priority=20, notes="Non-commercial licence on the model card: evaluation only. Do NOT set license_cleared without written legal clearance."),
    dict(key="nllb-200-distilled-600m", provider="nllb", model_name="facebook/nllb-200-distilled-600M",
         license="CC-BY-NC-4.0", runtime="local inference service", max_chars=3000, avg_latency_ms=1500, priority=90,
         notes="Research/evaluation baseline only. Non-commercial licence: do NOT set license_cleared without written legal clearance."),
    dict(key="cloud-translation-v2", provider="google", model_name="Cloud Translation Basic v2", license="commercial API terms",
         runtime="external API", is_external=True, max_chars=5000, cost_per_1k_chars=0.02, avg_latency_ms=400, priority=50,
         notes="External processor: only for projects with allow_external_processing."),
    dict(key="han-chat-qwen2.5-1.5b", provider="llamacpp", model_name="Qwen/Qwen2.5-1.5B-Instruct (GGUF Q4_K_M)", capability="chat",
         license="Apache-2.0", license_cleared=True, license_evidence="Model card states Apache-2.0 (verified at download).",
         runtime="local assistant service (llama.cpp, CPU)", enabled=True, deployment_status="deployed", max_chars=24000, avg_latency_ms=6000,
         priority=100, notes="Conversational help only; it never produces translations and is not a source of TNI policy."),
    dict(key="han-embed-e5-small", provider="transformers", model_name="intfloat/multilingual-e5-small", capability="embedding",
         license="MIT", license_cleared=True, license_evidence="Model card states MIT (verified at download).",
         runtime="local assistant service (transformers, CPU)", enabled=True, deployment_status="deployed", max_chars=2000, avg_latency_ms=150,
         priority=100, notes="Embeddings for knowledge-base retrieval (384 dimensions)."),
]

MOCK_MODEL = dict(
    key="dev-mock", provider="mock", model_name="deterministic development stub", license="n/a", license_cleared=True,
    license_evidence="Development stub; not a real translation engine.", runtime="in-process", enabled=True,
    deployment_status="deployed", max_chars=100_000, avg_latency_ms=1, priority=1000,
    notes="Only exists when HAN_ENV != production and HAN_ENABLE_MOCK_PROVIDER=1.",
)

# Words that must never appear in translator-facing structure, in addition to registry values.
DENYLIST_KEYS = {
    "provider_id", "model_id", "route_reason", "latency_ms", "estimated_cost", "provider", "model_key", "model",
    "routing", "fallback", "engine", "cost", "attempts",
}
DENYLIST_WORDS = {"madlad", "nllb", "afrinllb", "google", "gpt", "ctranslate2", "provider_id", "model_id", "route_reason",
                  "latency_ms", "estimated_cost"}

_ident_cache: Dict[str, Any] = {"ts": 0.0, "ids": set()}
_IDENT_TTL = 15.0


def invalidate_identifier_cache() -> None:
    _ident_cache["ts"] = 0.0


def registry_identifiers(db: Session) -> Set[str]:
    """All registry identifier VALUES (lower-cased) that must not appear in translator-facing structure."""
    now = time.monotonic()
    if now - _ident_cache["ts"] < _IDENT_TTL:
        return _ident_cache["ids"]
    ids: Set[str] = set()
    for m in db.execute(select(ModelRegistry)).scalars():
        for v in (m.key, m.provider, m.model_name):
            if v and len(v) >= 3:
                ids.add(v.lower())
                if "/" in v:
                    ids.add(v.rsplit("/", 1)[1].lower())
        if m.revision and len(m.revision) >= 7:
            ids.add(m.revision.lower())
    _ident_cache.update(ts=now, ids=ids)
    return ids


def get_model(db: Session, key: str) -> Optional[ModelRegistry]:
    return db.get(ModelRegistry, key)


def list_models(db: Session) -> List[ModelRegistry]:
    return list(db.execute(select(ModelRegistry).order_by(ModelRegistry.priority, ModelRegistry.key)).scalars())


def adapter_for(model: ModelRegistry) -> Optional[ProviderAdapter]:
    if model.key in ADAPTER_OVERRIDES:
        return ADAPTER_OVERRIDES[model.key]
    return get_adapter(model.provider)


def seed_registry(db: Session) -> int:
    """Insert missing default rows. Defaults are DISABLED, uncleared and not deployed (admin must act)."""
    added = 0
    for spec in DEFAULT_MODELS:
        if db.get(ModelRegistry, spec["key"]) is None:
            db.add(ModelRegistry(**spec))
            added += 1
    db.commit()
    invalidate_identifier_cache()
    return added


def ensure_mock_model(db: Session) -> bool:
    """Register the dev mock model only when explicitly allowed (never in production)."""
    if not get_settings().mock_provider_allowed:
        return False
    if db.get(ModelRegistry, MOCK_MODEL["key"]) is None:
        db.add(ModelRegistry(**MOCK_MODEL))
        db.commit()
        invalidate_identifier_cache()
    return True
