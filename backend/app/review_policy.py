"""Evidence thresholds for promoting a language direction (from Experimental to Assisted, and Assisted to Production).

Based on common translation-quality practice: independent native-speaker reviewers, a scored sample of meaningful size,
severity-weighted errors (MQM-style: no critical errors, a capped major-error rate), and agreement between reviewers.
These are decision aids. Meeting them marks a direction "ready for decision"; only an administrator changes its tier.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Dict, List, Optional

# A reviewer only counts as an independent reviewer once they have scored this many drafts in the direction.
MIN_SEGMENTS_PER_REVIEWER = 10


@dataclass(frozen=True)
class Threshold:
    tier: str
    min_reviewers: int
    min_segments: int
    min_content_types: int
    min_adequacy: float
    min_fluency: float
    max_major_rate: float
    max_reviewer_spread: float
    min_days: int


ASSISTED = Threshold("assisted", min_reviewers=2, min_segments=30, min_content_types=2, min_adequacy=4.0, min_fluency=3.8,
                     max_major_rate=0.10, max_reviewer_spread=1.0, min_days=0)
PRODUCTION = Threshold("production", min_reviewers=3, min_segments=100, min_content_types=3, min_adequacy=4.5, min_fluency=4.3,
                       max_major_rate=0.03, max_reviewer_spread=0.6, min_days=14)
THRESHOLDS = {"assisted": ASSISTED, "production": PRODUCTION}


def summarise(reviews: List[dict]) -> dict:
    """reviews: dicts with reviewer_id, adequacy, fluency, severity, content_type, created_at."""
    n = len(reviews)
    by_reviewer: Dict[str, List[dict]] = {}
    for r in reviews:
        by_reviewer.setdefault(str(r["reviewer_id"]), []).append(r)
    counted = {k: v for k, v in by_reviewer.items() if len(v) >= MIN_SEGMENTS_PER_REVIEWER}
    means = [mean(x["adequacy"] for x in v) for v in counted.values()]
    days = 0
    if n:
        stamps = [r["created_at"] for r in reviews]
        days = (max(stamps) - min(stamps)).days
    return {
        "segments": n,
        "reviewers": len(counted),
        "reviewers_total": len(by_reviewer),
        "content_types": len({r["content_type"] for r in reviews}),
        "mean_adequacy": round(mean(r["adequacy"] for r in reviews), 2) if n else None,
        "mean_fluency": round(mean(r["fluency"] for r in reviews), 2) if n else None,
        "critical_errors": sum(r["severity"] == "critical" for r in reviews),
        "major_rate": round(sum(r["severity"] in ("major", "critical") for r in reviews) / n, 3) if n else None,
        "reviewer_spread": round(max(means) - min(means), 2) if len(means) > 1 else None,
        "days": days,
    }


def evaluate(summary: dict, th: Threshold) -> List[dict]:
    def check(key, label, value, required, met, unit=""):
        return {"key": key, "label": label, "value": value, "required": required, "met": bool(met), "unit": unit}

    s = summary
    return [
        check("reviewers", "Independent reviewers", s["reviewers"], f">= {th.min_reviewers}", s["reviewers"] >= th.min_reviewers),
        check("segments", "Scored drafts", s["segments"], f">= {th.min_segments}", s["segments"] >= th.min_segments),
        check("content_types", "Content types covered", s["content_types"], f">= {th.min_content_types}", s["content_types"] >= th.min_content_types),
        check("adequacy", "Mean adequacy (1-5)", s["mean_adequacy"], f">= {th.min_adequacy}", (s["mean_adequacy"] or 0) >= th.min_adequacy),
        check("fluency", "Mean fluency (1-5)", s["mean_fluency"], f">= {th.min_fluency}", (s["mean_fluency"] or 0) >= th.min_fluency),
        check("critical", "Critical errors", s["critical_errors"], "0", s["critical_errors"] == 0),
        check("major", "Major or critical error rate", s["major_rate"], f"<= {th.max_major_rate:.0%}",
              s["major_rate"] is not None and s["major_rate"] <= th.max_major_rate),
        check("agreement", "Reviewer disagreement (adequacy spread)", s["reviewer_spread"], f"<= {th.max_reviewer_spread}",
              s["reviewer_spread"] is not None and s["reviewer_spread"] <= th.max_reviewer_spread),
        check("days", "Evidence collected over (days)", s["days"], f">= {th.min_days}", s["days"] >= th.min_days),
    ]


def readiness(summary: dict, current_tier: str, technical_status: str) -> dict:
    """Highest tier whose every criterion is met, plus the checklist for the next tier above the current one."""
    ladder = ["experimental", "assisted", "production"]
    results = {name: evaluate(summary, th) for name, th in THRESHOLDS.items()}
    passes = {name: all(c["met"] for c in checks) for name, checks in results.items()}
    ready: Optional[str] = None
    if passes["assisted"] and current_tier == "experimental":
        ready = "assisted"
    if passes["production"] and technical_status == "passed" and current_tier == "assisted":
        ready = "production"
    nxt = ladder[ladder.index(current_tier) + 1] if current_tier in ladder[:-1] else None
    return {"ready_for": ready, "next_tier": nxt, "criteria": results.get(nxt, []) if nxt else [],
            "production_requires_clean_technical_check": technical_status != "passed"}
