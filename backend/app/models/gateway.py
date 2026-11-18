"""Model gateway (INTERNAL): normalises requests, enforces quotas, applies per-attempt timeouts,
bounded retries and invisible fallback. Writes routing_events / usage_records in independent
transactions so failures are still recorded. Never returns provider identity to callers other than
as an internal `GatewayResult` (which public serializers must never see)."""
from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import SessionLocal
from ..logging_config import request_id_var
from ..providers.base import ProviderError
from .db import Project, RoutingEvent, UsageRecord
from .internal_schemas import Candidate, GatewayResult, ProviderRequest
from .router import DirectionUnsupported, plan_route

log = logging.getLogger("han.gateway")
_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="han-provider")


class TranslationUnavailable(Exception):
    """No provider could produce a translation (generic to callers; detail lives in routing_events)."""


class QuotaExceeded(Exception):
    pass


__all__ = ["ModelGateway", "TranslationUnavailable", "QuotaExceeded", "DirectionUnsupported", "month_start", "usage_totals"]


def month_start(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage_totals(db: Session, project_id: uuid.UUID) -> Dict[str, float]:
    chars, cost = db.execute(
        select(func.coalesce(func.sum(UsageRecord.chars), 0), func.coalesce(func.sum(UsageRecord.cost), 0.0)).where(
            UsageRecord.project_id == project_id, UsageRecord.created_at >= month_start()
        )
    ).one()
    return {"chars": int(chars), "cost": float(cost)}


def _write_event(**fields: Any) -> uuid.UUID:
    with SessionLocal() as s:
        ev = RoutingEvent(**fields)
        s.add(ev)
        s.commit()
        return ev.id


def _write_usage(**fields: Any) -> None:
    with SessionLocal() as s:
        s.add(UsageRecord(**fields))
        s.commit()


class ModelGateway:
    def __init__(self, timeout_s: Optional[float] = None, retries: Optional[int] = None, backoff_s: Optional[float] = None):
        s = get_settings()
        self.timeout_s = s.provider_timeout_s if timeout_s is None else timeout_s
        self.retries = s.provider_retries if retries is None else retries
        self.backoff_s = s.provider_retry_backoff_s if backoff_s is None else backoff_s

    # ------------------------------------------------------------------ quotas
    def _check_quota(self, db: Session, project: Project, text_len: int) -> Dict[str, float]:
        used = usage_totals(db, project.id)
        if project.monthly_char_quota is not None and used["chars"] + text_len > project.monthly_char_quota:
            raise QuotaExceeded("character quota")
        return used

    def _after_usage(self, db: Session, project: Project, before: Dict[str, float], added_cost: float) -> None:
        limit = project.monthly_spend_limit
        if limit is None or float(limit) <= 0:
            return
        threshold = float(limit) * project.spend_alert_pct / 100.0
        if before["cost"] < threshold <= before["cost"] + added_cost:
            audit.record("quota.alert", outcome="warning", object_type="project", project_id=project.id,
                         details={"kind": "spend_threshold", "pct": project.spend_alert_pct})

    # ------------------------------------------------------------------ main entry
    def translate(
        self,
        db: Session,
        project: Project,
        source: str,
        target: str,
        text: str,
        *,
        user_id: Optional[uuid.UUID] = None,
        context: Optional[str] = None,
        domain: Optional[str] = None,
        glossary: Optional[List[Dict[str, str]]] = None,
        segment_id: Optional[uuid.UUID] = None,
        only_model: Optional[str] = None,
        evaluation: bool = False,
        technical_test: bool = False,
    ) -> GatewayResult:
        request_id = request_id_var.get()
        base = dict(request_id=request_id, project_id=project.id, user_id=user_id, segment_id=segment_id,
                    source_code=source, target_code=target, chars=len(text))
        used = self._check_quota(db, project, len(text))
        plan = plan_route(db, project, source, target, len(text), only_model=only_model, evaluation=evaluation, technical_test=technical_test)

        candidates: List[Candidate] = []
        limit = project.monthly_spend_limit
        spend_blocked = 0
        for c in plan.candidates:
            est = len(text) * c.model.cost_per_1k_chars / 1000.0
            if limit is not None and used["cost"] + est > float(limit):
                spend_blocked += 1
                continue
            candidates.append(c)
        if plan.candidates and not candidates and spend_blocked:
            raise QuotaExceeded("spend limit")
        if not candidates:
            _write_event(**base, attempt_no=0, status="no_route", error_category="no_eligible_provider",
                         route_reason="; ".join(f"{r.model_key}:{r.reason}" for r in plan.rejections)[:2000])
            raise TranslationUnavailable("no eligible provider")

        attempt_no = 0
        event_ids: List[uuid.UUID] = []
        for idx, cand in enumerate(candidates):
            for retry in range(self.retries + 1):
                attempt_no += 1
                req = ProviderRequest(text=text, source_code=source, target_code=target, context=context, domain=domain,
                                      glossary=glossary or [], request_id=request_id, timeout_s=self.timeout_s)
                started = time.perf_counter()
                status, category, result = "success", None, None
                try:
                    fut = _executor.submit(cand.adapter.translate, req)
                    result = fut.result(timeout=self.timeout_s + 0.25)
                except FutureTimeout:
                    status, category = "timeout", "timeout"
                except ProviderError as e:
                    status, category = ("timeout" if e.category == "timeout" else "error"), e.category
                except Exception:  # adapter bug / unexpected failure: treated as provider error
                    log.exception("provider adapter raised unexpectedly")
                    status, category = "error", "unexpected"
                elapsed = int((time.perf_counter() - started) * 1000)
                registry_cost = len(text) * cand.model.cost_per_1k_chars / 1000.0
                cost = (registry_cost or result.estimated_cost) if result else 0.0
                ev_id = _write_event(
                    **base, attempt_no=attempt_no, model_key=cand.model_key, status=status, error_category=category,
                    latency_ms=result.latency_ms if result else elapsed, estimated_cost=cost,
                    route_reason=cand.reason, fallback=idx > 0,
                )
                event_ids.append(ev_id)
                _write_usage(project_id=project.id, model_key=cand.model_key, source_code=source, target_code=target,
                             chars=len(text) if result else 0, cost=cost, latency_ms=elapsed, success=result is not None)
                if result is not None:
                    self._after_usage(db, project, used, cost)
                    return GatewayResult(
                        text=result.text, model_key=cand.model_key, attempts=attempt_no, fallback_used=idx > 0,
                        latency_ms=result.latency_ms, estimated_cost=cost, routing_event_ids=event_ids,
                    )
                retryable = category in ("timeout", "unavailable", "rate_limited")
                if not retryable:
                    break
                if retry < self.retries and self.backoff_s:
                    time.sleep(self.backoff_s)
        log.warning("all providers failed", extra={"attempts": attempt_no})
        raise TranslationUnavailable("all providers failed")
