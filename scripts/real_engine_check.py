#!/usr/bin/env python3
"""Real-engine check: HAN backend + a RUNNING inference service (no mock provider).

    # 1. start the inference service with real weights (see README "Running a real engine")
    # 2. then:
    ~/.han-venvs/han/bin/python scripts/real_engine_check.py --url http://127.0.0.1:9000 --token-file /tmp/han_inf_token

Starts an embedded PostgreSQL and the HAN backend with the mock provider DISABLED, then verifies that:
  * before an administrator enables a model, translation is unavailable (nothing is fabricated);
  * after enabling (licence evidence + deployed + enabled) a real translation is produced through the normal router/gateway;
  * translators never see engine identity, while the technical administrator can inspect the routing record;
  * human edit -> approval -> Translation Memory still works with real output.
Setting `license_cleared` here records the model card's licence as evidence for a DEVELOPMENT database only. It is not legal clearance.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_e2e import free_port, wait_http  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PG_DIR = Path.home() / ".han-venvs" / f"real-pg-{os.getpid()}"
ADMIN_PW = "real-engine-admin-pw-123"
MODEL_KEY = "madlad-400-3b-mt"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:9000")
    ap.add_argument("--token-file", required=True)
    args = ap.parse_args()
    token = Path(args.token_file).read_text().strip()

    import httpx
    import pgserver

    failures = []

    def check(label, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + str(detail)[:300]) if (detail and not ok) else ''}")
        if not ok:
            failures.append(label)

    PG_DIR.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(PG_DIR, cleanup_mode="delete")
    proc = None
    try:
        env = {**os.environ, "HAN_ENV": "development", "HAN_ENABLE_MOCK_PROVIDER": "0", "HAN_JOBS_EAGER": "1",
               "HAN_DATABASE_URL": server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1),
               "HAN_SECRET_KEY": "real-secret-" + "y" * 32, "HAN_LOG_LEVEL": "WARNING", "PYTHONPATH": str(BACKEND),
               "HAN_MADLAD_URL": args.url, "HAN_INFERENCE_TOKEN": token, "HAN_PROVIDER_TIMEOUT_S": "180", "HAN_PROVIDER_RETRIES": "0",
               "HAN_BOOTSTRAP_TECH_ADMIN_EMAIL": "ops@example.test", "HAN_BOOTSTRAP_TECH_ADMIN_PASSWORD": ADMIN_PW}
        py = sys.executable
        subprocess.run([py, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True)
        seed = subprocess.run([py, "-m", "app.seed", "--demo"], cwd=BACKEND, env=env, check=True, capture_output=True, text=True).stdout
        pw = next(line.split("shown once): ")[1].strip() for line in seed.splitlines() if "translator@example.test" in line)
        port = free_port()
        proc = subprocess.Popen([py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=BACKEND, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{port}"
        wait_http(base + "/healthz")

        tr = httpx.Client(base_url=base, timeout=300)
        r = tr.post("/v1/auth/login", json={"email": "translator@example.test", "password": pw})
        th = {"X-CSRF-Token": r.json()["csrf_token"]}
        pid = tr.get("/v1/projects").json()[0]["id"]
        ad = httpx.Client(base_url=base, timeout=300)
        r = ad.post("/v1/auth/login", json={"email": "ops@example.test", "password": ADMIN_PW})
        ah = {"X-CSRF-Token": r.json()["csrf_token"]}
        body = {"project_id": pid, "source_language": "en", "target_language": "de", "text": "Good morning. The meeting is on 12 May at the main office."}

        print("\nBefore an administrator enables the model")
        r = tr.post("/v1/translate", headers=th, json=body)
        check("translation is unavailable (nothing fabricated)", r.status_code == 503 and r.json()["detail"]["code"] == "translation_unavailable", r.text)

        print("\nAdministrator enables the model (licence evidence + deployed + enabled)")
        r = ad.patch(f"/v1/admin/models/{MODEL_KEY}", headers=ah, json={
            "license": "Apache-2.0", "license_cleared": True, "deployment_status": "deployed", "enabled": True,
            "license_evidence": "Model card google/madlad400-3b-mt lists Apache-2.0 (checked in development). NOT legal clearance: TNI legal must confirm before production."})
        check("model enabled via the protected admin API", r.status_code == 200 and r.json()["enabled"] is True, r.text)

        print("\nReal translation")
        t0 = time.time()
        r = tr.post("/v1/translate", headers=th, json=body)
        took = time.time() - t0
        j = r.json()
        check("translate returns a draft", r.status_code == 201 and j.get("status") == "draft", r.text)
        out = j.get("translated_text", "")
        print(f"    source : {body['text']}\n    HAN    : {out}   ({took:.1f}s)")
        check("output is a real translation (not the mock stub, not an echo)", bool(out) and "[MOCK" not in out and out.strip() != body["text"], out)
        check("German output keeps the date", "12" in out and "Mai" in out, out)
        check("no number warnings on a correct translation", not [w for w in j.get("warnings", []) if w["type"] == "number"])
        check("translator payload has no engine identity", "madlad" not in r.text.lower() and "provider" not in r.text.lower())

        events = ad.get("/v1/admin/routing-events").json()
        ok_ev = [e for e in events if e["status"] == "success"]
        check("technical admin sees the routing record", bool(ok_ev) and ok_ev[0]["model_key"] == MODEL_KEY and ok_ev[0]["latency_ms"] > 0, events)
        print(f"    routing record (admin only): model={ok_ev[0]['model_key']} latency={ok_ev[0]['latency_ms']}ms reason={ok_ev[0]['route_reason'][:70]}")

        print("\nHuman review and approval with real output")
        v = tr.post(f"/v1/translations/{j['translation_id']}/versions", headers=th, json={"target_text": out, "parent_version_id": j["version_id"], "change_note": "reviewed"})
        a = tr.post(f"/v1/versions/{v.json()['version']['version_id']}/approve", headers=th, json={"decision": "approved"})
        check("approval recorded", a.status_code == 201, a.text)
        again = tr.post("/v1/translate", headers=th, json=body).json()
        check("approved translation now offered as an exact TM match", any(m["match_percent"] == 100 for m in again.get("tm_matches", [])), again)

        print("\nHAN chat and a second language")
        c = tr.post("/v1/chat", headers=th, json={"project_id": pid, "message": "Translate this text from English to Swahili: Wash your hands with soap for at least twenty seconds."})
        reply = c.json().get("translation") or {}
        print(f"    HAN chat (sw): {reply.get('translated_text')}")
        check("chat returns a real Swahili draft", c.status_code == 200 and "[MOCK" not in reply.get("translated_text", "[MOCK") and bool(reply), c.text)
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        server.cleanup()
        shutil.rmtree(PG_DIR, ignore_errors=True)
    print("\nRESULT:", "PASS" if not failures else f"FAIL {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
