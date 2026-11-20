"""Language registry and pair-capability matrix.

Coverage (what the engine's checkpoint can emit) is kept separate from availability (what HAN lets translators use):
  Stage 1  technical verification  -> language_directions.technical_status   (untested | passed | degraded | failed)
  Stage 2  human evaluation        -> language_directions.validation_status  (pending | in_review | validated | rejected)
  Stage 3/4 availability           -> language_directions.readiness_tier     (unsupported | experimental | assisted | production)
A direction is never enabled just because the engine lists the language: an administrator sets the tier.
Engine language tokens live in languages.model_codes and are exposed only through the engine-protected admin endpoint.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models.db import Language, LanguageDirection
from .providers.language_codes import madlad_token

CATALOG = Path(__file__).resolve().parent / "data" / "language_catalog.json"
PIVOT = "en"
MIN_ROUNDTRIP = 0.4  # one short sentence is a noisy signal; this only gates Experimental (controlled testing), never Production

AVAILABILITY = {
    "production": "enabled", "assisted": "enabled_with_review", "experimental": "controlled_testing", "unsupported": "not_enabled",
}


def availability(tier: str) -> str:
    return AVAILABILITY.get(tier, "not_enabled")


def load_catalog() -> dict:
    return json.loads(CATALOG.read_text())


def seed_language_catalog(db: Session) -> int:
    """Register every language the checkpoint audit found (idempotent). Existing curated rows keep their names."""
    cat = load_catalog()["languages"]
    existing = {l.code: l for l in db.execute(select(Language)).scalars()}
    added = 0
    for code, info in cat.items():
        row = existing.get(code)
        if row is None:
            row = Language(code=code, display_name=info["name"], script=info["script"], active=True, reviewed=False)
            db.add(row)
            added += 1
        row.native_name = row.native_name or info["native_name"]
        row.script = row.script or info["script"]
        codes = dict(row.model_codes or {})
        codes["madlad"] = madlad_token(code) or code
        row.model_codes = codes
    db.commit()
    return added


def import_probe_evidence(db: Session) -> int:
    """Record Stage-1 results as en<->X direction rows. New rows start as `unsupported` (not enabled)."""
    cat = load_catalog()
    stamp = datetime.fromisoformat(cat["probed_at"]) if cat.get("probed_at") else datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    langs = set(db.execute(select(Language.code)).scalars())
    n = 0
    for code, info in cat["languages"].items():
        ev = info.get("probe")
        if not ev or code == PIVOT or code not in langs or PIVOT not in langs:
            continue
        for src, tgt in ((PIVOT, code), (code, PIVOT)):
            row = db.get(LanguageDirection, (src, tgt))
            if row is None:
                row = LanguageDirection(source_code=src, target_code=tgt, readiness_tier="unsupported")
                db.add(row)
            row.technical_status = ev["status"]
            row.technical_checked_at = stamp
            row.technical_detail = {"similarity": ev.get("similarity"), "flags": ev.get("flags", []), "probe": "good-morning sentence, both directions"}
            n += 1
    db.commit()
    return n


def pilot_candidates(db: Session) -> List[str]:
    """Languages that may be offered as Experimental: curated (native name known), probe passed, round trip plausible."""
    cat = load_catalog()["languages"]
    out = []
    for code, info in cat.items():
        ev = info.get("probe")
        if code != PIVOT and info["native_name"] and ev and ev["status"] == "passed" and (ev.get("similarity") or 0) >= MIN_ROUNDTRIP:
            out.append(code)
    return sorted(out)


def enable_pilot_directions(db: Session, codes: Optional[List[str]] = None, user_id=None) -> int:
    """Mark en<->X as EXPERIMENTAL (controlled testing) where both legs passed Stage 1 and the direction is not enabled yet."""
    n = 0
    for code in codes if codes is not None else pilot_candidates(db):
        for src, tgt in ((PIVOT, code), (code, PIVOT)):
            row = db.get(LanguageDirection, (src, tgt))
            if row is None or row.technical_status != "passed" or row.readiness_tier != "unsupported":
                continue
            row.readiness_tier = "experimental"
            row.review_note = "Controlled testing: technically verified, not yet evaluated by TNI translators. Review every draft carefully."
            row.updated_by = user_id
            n += 1
    db.commit()
    return n


def enable_all_directions(db: Session, user_id=None) -> int:
    """Open every English<->X direction that has not failed its technical check for CONTROLLED TESTING (experimental)."""
    n = 0
    rows = db.execute(select(LanguageDirection).where(LanguageDirection.readiness_tier == "unsupported",
                                                      LanguageDirection.technical_status != "failed")).scalars().all()
    for row in rows:
        if PIVOT not in (row.source_code, row.target_code):
            continue
        row.readiness_tier = "experimental"
        row.review_note = ("Controlled testing: the technical check showed weaker output for this language. Expect errors and review every draft carefully."
                           if row.technical_status == "degraded" else
                           "Controlled testing: not yet evaluated by TNI translators. Review every draft carefully.")
        row.updated_by = user_id
        n += 1
    db.commit()
    return n


def language_support(db: Session) -> List[Dict]:
    """One row per active language with its best availability against the pivot, for the public Languages page."""
    rank = {"production": 3, "assisted": 2, "experimental": 1, "unsupported": 0}
    best: Dict[str, str] = {}
    for d in db.execute(select(LanguageDirection)).scalars():
        for code in (d.source_code, d.target_code):
            if rank[d.readiness_tier] > rank.get(best.get(code, "unsupported"), 0):
                best[code] = d.readiness_tier
    rows = []
    for l in db.execute(select(Language).where(Language.active.is_(True)).order_by(Language.display_name)).scalars():
        tier = best.get(l.code, "unsupported")
        rows.append({"code": l.code, "name": l.display_name, "native_name": l.native_name, "script": l.script, "tier": tier,
                     "availability": availability(tier), "reviewed": l.reviewed})
    return rows


def expertise_language(db: Session, code: str) -> Language:
    """The active, non-English language a translator may claim as expertise; raises ValueError otherwise."""
    code = (code or "").strip().lower().replace("_", "-")
    lang = db.get(Language, code)
    if lang is None or not lang.active or code == PIVOT:
        raise ValueError("unknown_language")
    return lang


def ensure_pair(db: Session, code: str) -> None:
    """Make sure both directions English->X and X->English exist (created as not yet enabled when new)."""
    for src, tgt in ((PIVOT, code), (code, PIVOT)):
        if db.get(LanguageDirection, (src, tgt)) is None:
            db.add(LanguageDirection(source_code=src, target_code=tgt, readiness_tier="unsupported"))


def translator_pairs(db: Session, user) -> Optional[Dict]:
    """The translator's language of expertise and its two directions, for HAN to use as defaults."""
    code = getattr(user, "expertise_language", None)
    if not code:
        return None
    lang = db.get(Language, code)
    if lang is None:
        return None
    pairs = []
    for src, tgt in ((PIVOT, code), (code, PIVOT)):
        d = db.get(LanguageDirection, (src, tgt))
        pairs.append({"source": src, "target": tgt, "tier": d.readiness_tier if d else "unsupported"})
    return {"code": code, "name": lang.display_name, "pairs": pairs}
