#!/usr/bin/env python3
"""Benchmark runner: translate a reviewer-curated segment set and write a results CSV for human scoring.

    cd backend && ~/.han-venvs/han/bin/python ../scripts/benchmark.py --input ../data/benchmark/example.csv \
        --output /tmp/results.csv --project-id <uuid> [--model <registry key>] [--evaluation]

Input CSV columns:  source_lang, target_lang, source_text, reference_text (optional), domain (optional)
Output CSV adds:    model_key, model_output, latency_ms, chars, cost  (internal, for the evaluation lead)
                    and EMPTY reviewer columns: adequacy, fluency, terminology, critical_error, post_edit_effort, notes
                    (spec §14.1 rubric: scale definitions and acceptance thresholds are set by the evaluation lead).

Notes
* Output files contain provider/model identity: keep them in controlled internal storage, never share with translators.
* `--evaluation` lets a licence-uncleared model be measured (refused when HAN_ENV=production). Benchmarking is not
  production use; do not route client content to such a model.
* Uses the real model gateway, so quotas, data-policy and routing rules apply as in the application.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models.db import Project  # noqa: E402
from app.models.gateway import ModelGateway, QuotaExceeded, TranslationUnavailable  # noqa: E402
from app.models.router import DirectionUnsupported  # noqa: E402

REVIEWER_COLUMNS = ["adequacy", "fluency", "terminology", "critical_error", "post_edit_effort", "notes"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--project-id", required=True, help="project whose data policy / quotas apply to the run")
    ap.add_argument("--model", help="restrict routing to one registry key (e.g. to compare candidates)")
    ap.add_argument("--evaluation", action="store_true", help="skip the licence gate (non-production only)")
    args = ap.parse_args()

    with open(args.input, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    required = {"source_lang", "target_lang", "source_text"}
    if not rows or not required <= set(rows[0]):
        print(f"input must have columns: {sorted(required)}", file=sys.stderr)
        return 2

    out_rows = []
    with SessionLocal() as db:
        project = db.get(Project, uuid.UUID(args.project_id))
        if project is None:
            print("project not found", file=sys.stderr)
            return 2
        gateway = ModelGateway()
        for i, row in enumerate(rows, start=1):
            started = time.perf_counter()
            entry = {**row, "model_key": "", "model_output": "", "latency_ms": "", "chars": len(row["source_text"]), "cost": "", "status": "ok"}
            try:
                res = gateway.translate(db, project, row["source_lang"].lower(), row["target_lang"].lower(), row["source_text"],
                                        only_model=args.model, evaluation=args.evaluation)
                entry.update(model_key=res.model_key, model_output=res.text, latency_ms=res.latency_ms, cost=res.estimated_cost)
            except DirectionUnsupported:
                entry["status"] = "direction_unsupported"
            except (TranslationUnavailable, QuotaExceeded) as e:
                entry["status"] = type(e).__name__
            entry.setdefault("elapsed_ms", int((time.perf_counter() - started) * 1000))
            for col in REVIEWER_COLUMNS:
                entry[col] = ""
            out_rows.append(entry)
            print(f"[{i}/{len(rows)}] {entry['status']}")

    fieldnames = list(out_rows[0].keys())
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
