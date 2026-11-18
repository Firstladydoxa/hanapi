"""Model router (INTERNAL): registry-driven eligibility + scoring. Returns ordered candidates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from .db import LanguageDirection, ModelDirectionScore, ModelRegistry, Project, RoutingEvent
from .internal_schemas import Candidate, Rejection, RoutePlan
from .registry import adapter_for, list_models

TIER_FACTOR = {"production": 1.0, "assisted": 0.95, "experimental": 0.8}


class DirectionUnsupported(Exception):
    pass


def direction_tier(db: Session, source: str, target: str) -> str:
    row = db.get(LanguageDirection, (source, target))
    return row.readiness_tier if row else "unsupported"


def provider_error_rates(db: Session) -> Dict[str, Tuple[int, int]]:
    """model_key -> (attempts, failures) within the health window (recent routing attempts)."""
    s = get_settings()
    since = datetime.now(timezone.utc) - timedelta(minutes=s.health_window_minutes)
    rows = db.execute(
        select(RoutingEvent.model_key, func.count(), func.count().filter(RoutingEvent.status != "success"))
        .where(RoutingEvent.created_at >= since, RoutingEvent.model_key.is_not(None), RoutingEvent.status != "no_route")
        .group_by(RoutingEvent.model_key)
    ).all()
    return {k: (a, f) for k, a, f in rows}


def is_healthy(rates: Dict[str, Tuple[int, int]], key: str) -> bool:
    s = get_settings()
    attempts, failures = rates.get(key, (0, 0))
    return attempts < s.health_min_attempts or failures / attempts <= s.health_max_error_rate


def _model_supports_languages(model: ModelRegistry, source: str, target: str) -> bool:
    if not model.languages:
        return True
    langs = {str(x).lower() for x in model.languages}
    return source in langs and target in langs


def plan_route(
    db: Session,
    project: Project,
    source: str,
    target: str,
    text_len: int,
    *,
    only_model: Optional[str] = None,
    evaluation: bool = False,
    technical_test: bool = False,
) -> RoutePlan:
    """Raises DirectionUnsupported when the direction is unsupported (or experimental without pilot opt-in).

    `technical_test=True` (administrator language checks only) skips the readiness-tier gate so a direction can be verified
    BEFORE it is enabled; every other gate (licence, health, data policy, language coverage) still applies.

    `evaluation=True` (benchmark tooling only, never in production) skips the licence gate so a
    research-only model can be measured; it still requires the model to be enabled and deployed.
    """
    s = get_settings()
    if evaluation and s.is_production:
        raise PermissionError("evaluation routing is not available in production")
    tier = direction_tier(db, source, target)
    if not technical_test:
        if tier == "unsupported":
            raise DirectionUnsupported(tier)
        if tier == "experimental" and not project.pilot_opt_in:
            raise DirectionUnsupported("experimental-without-pilot")

    scores = {
        r.model_key: r.benchmark_score
        for r in db.execute(
            select(ModelDirectionScore).where(ModelDirectionScore.source_code == source, ModelDirectionScore.target_code == target)
        ).scalars()
    }
    rates = provider_error_rates(db)
    candidates: List[Candidate] = []
    rejections: List[Rejection] = []

    for m in list_models(db):
        if only_model and m.key != only_model:
            continue
        reject = None
        adapter = adapter_for(m)
        if m.capability != "translation":
            continue  # conversational and embedding models are never translation candidates
        if not m.enabled:
            reject = "provider_disabled"
        elif not m.license_cleared and not evaluation:
            reject = "license_not_cleared"
        elif m.deployment_status != "deployed":
            reject = "not_deployed"
        elif adapter is None or not adapter.configured():
            reject = "adapter_unavailable"
        elif m.provider == "mock" and not s.mock_provider_allowed:
            reject = "mock_not_allowed"
        elif not _model_supports_languages(m, source, target) or not adapter.supports(source, target):
            reject = "direction_not_covered"
        elif (m.is_external or adapter.external) and not project.allow_external_processing:
            reject = "data_policy_blocks_external"
        elif text_len > m.max_chars:
            reject = "context_limit_exceeded"
        elif not is_healthy(rates, m.key):
            reject = "unhealthy_error_rate"
        if reject:
            rejections.append(Rejection(m.key, reject))
            continue
        bench = scores.get(m.key)
        bench_v = 0.4 if bench is None else float(bench)  # unevaluated direction: low-confidence default
        latency_n = 1.0 / (1.0 + m.avg_latency_ms / 1000.0)
        cost_n = 1.0 / (1.0 + m.cost_per_1k_chars * 100.0)
        score = TIER_FACTOR.get(tier, 0.5) * (0.6 * bench_v + 0.2 * latency_n + 0.2 * cost_n)
        reason = (
            f"tier={tier}; benchmark={'n/a' if bench is None else round(float(bench), 3)}; "
            f"latency_n={latency_n:.2f}; cost_n={cost_n:.2f}; score={score:.3f}"
        )
        candidates.append(Candidate(m.key, m.provider, score, reason, m, adapter))

    candidates.sort(key=lambda c: (-c.score, c.model.priority, c.model_key))
    return RoutePlan(candidates=candidates, rejections=rejections, tier=tier)
