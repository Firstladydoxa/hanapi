#!/usr/bin/env python3
"""End-to-end smoke test: embedded PostgreSQL -> alembic -> seed -> uvicorn -> HTTP workflow. Prints PASS/FAIL.

    ~/.han-venvs/han/bin/python scripts/smoke_e2e.py [--frontend]

--ui SCRIPT.mjs  (implies --frontend) runs a Node/Playwright script against the live stack with HAN_URL,
HAN_TRANSLATOR_EMAIL/PASSWORD and HAN_TECH_EMAIL/PASSWORD in its environment.

--frontend additionally starts the built Next.js app (frontend/.next must exist: `npm run build`) and repeats the
login + translate flow THROUGH the Next.js /v1 proxy, as a browser would.
Uses the development mock provider (output is labelled "[MOCK DRAFT]", it is not a real translation).
No background process or temporary database is left behind.
"""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PG_DIR = Path.home() / ".han-venvs" / f"smoke-pg-{os.getpid()}"
PASSWORD = "smoke-test-password-123"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 60.0) -> None:
    import httpx

    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except Exception:
            time.sleep(0.4)
    raise RuntimeError(f"timed out waiting for {url}")


def main() -> int:
    ui_script = sys.argv[sys.argv.index("--ui") + 1] if "--ui" in sys.argv else None
    use_frontend = "--frontend" in sys.argv or ui_script is not None
    import httpx
    import pgserver

    PG_DIR.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(PG_DIR, cleanup_mode="delete")
    procs: list[subprocess.Popen] = []
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if (detail and not ok) else ''}")
        if not ok:
            failures.append(label)

    try:
        env = {**os.environ, "HAN_ENV": "development", "HAN_ENABLE_MOCK_PROVIDER": "1", "HAN_JOBS_EAGER": "1",
               "HAN_DATABASE_URL": server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1),
               "HAN_SECRET_KEY": "smoke-secret-" + "x" * 32, "HAN_LOG_LEVEL": "WARNING", "HAN_BOOTSTRAP_TECH_ADMIN_EMAIL": "ops@example.test",
               "HAN_BOOTSTRAP_TECH_ADMIN_PASSWORD": PASSWORD, "PYTHONPATH": str(BACKEND)}
        py = sys.executable
        subprocess.run([py, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True)
        seed = subprocess.run([py, "-m", "app.seed", "--demo"], cwd=BACKEND, env=env, check=True, capture_output=True, text=True).stdout
        translator_pw = next(line.split("shown once): ")[1].strip() for line in seed.splitlines() if "translator@example.test" in line)
        print("Seeded database (translator password was generated and is used only in this run).")

        port = free_port()
        procs.append(subprocess.Popen([py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=BACKEND, env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        base = f"http://127.0.0.1:{port}"
        wait_http(base + "/healthz")
        print(f"Backend up on {base}")

        def flow(root: str, label: str, sentence: str) -> None:
            print(f"\nWorkflow via {label}")
            c = httpx.Client(base_url=root, timeout=30)
            r = c.post("/v1/auth/login", json={"email": "translator@example.test", "password": translator_pw})
            check("login", r.status_code == 200, r.text)
            h = {"X-CSRF-Token": r.json()["csrf_token"]}
            check("unauthenticated request rejected", httpx.get(root + "/v1/projects").status_code == 401)
            projects = c.get("/v1/projects").json()
            check("sees exactly its authorised project", [p["name"] for p in projects] == ["Demo project"])
            pid = projects[0]["id"]
            t = c.post("/v1/translate", headers=h, json={"project_id": pid, "source_language": "en", "target_language": "de", "text": sentence})
            check("translate returns a draft requiring review", t.status_code == 201 and t.json()["status"] == "draft" and t.json()["review_required"], t.text)
            body = t.json()
            leak = [k for k in ("provider", "model", "route", "latency", "cost") if k in t.text.lower().replace("[mock draft]", "")]
            check("response carries no engine/routing metadata", not leak, str(leak))
            v = c.post(f"/v1/translations/{body['translation_id']}/versions", headers=h,
                       json={"target_text": "Der Start ist am 12. Mai.", "parent_version_id": body["version_id"], "change_note": "human edit"})
            check("edit saved as a NEW version", v.status_code == 201 and v.json()["version"]["version_number"] == 2, v.text)
            tm0 = c.get("/v1/tm/search", params={"project_id": pid, "source_language": "en", "target_language": "de", "q": sentence}).json()
            check("draft is not in Translation Memory", tm0["results"] == [])
            a = c.post(f"/v1/versions/{v.json()['version']['version_id']}/approve", headers=h, json={"decision": "approved"})
            check("human approval recorded", a.status_code == 201 and a.json()["version"]["approval_state"] == "approved", a.text)
            tm1 = c.get("/v1/tm/search", params={"project_id": pid, "source_language": "en", "target_language": "de", "q": sentence}).json()
            check("approved version is in Translation Memory with provenance", len(tm1["results"]) == 1 and tm1["results"][0]["provenance"]["version_id"] == v.json()["version"]["version_id"])
            chat = c.post("/v1/chat", headers=h, json={"project_id": pid, "message": "Translate this text from English to German: Good morning"})
            check("HAN chat returns a suggested translation", chat.status_code == 200 and chat.json()["reply"].startswith("Here is my suggested translation"), chat.text)
            deflect = c.post("/v1/chat", headers=h, json={"project_id": pid, "message": "Which engine did you use?"})
            check("HAN does not disclose the engine", "HAN manages the translation process" in deflect.json()["reply"])
            job = c.post("/v1/translation-jobs", headers=h, json={"project_id": pid, "source_language": "en", "target_language": "de", "text": "One.\n\nTwo."})
            check("translation job created and processed", job.status_code == 201 and job.json()["status"] == "ready", job.text)
            check("translator cannot reach admin or engine data",
                  c.get("/v1/admin/users").status_code == 403 and c.get("/v1/admin/routing-events").status_code == 403)
            check("approval without CSRF token refused", c.post(f"/v1/versions/{body['version_id']}/approve", json={"decision": "approved"}).status_code == 403)

        flow(base, "backend API", "The launch is on 12 May.")

        admin = httpx.Client(base_url=base, timeout=30)
        r = admin.post("/v1/auth/login", json={"email": "ops@example.test", "password": PASSWORD})
        events = admin.get("/v1/admin/routing-events").json()
        check("technical administrator can inspect routing records", r.status_code == 200 and len(events) >= 1 and "latency_ms" in events[0])

        if use_frontend:
            fport = free_port()
            fenv = {**os.environ, "HAN_BACKEND_URL": base, "PORT": str(fport), "HOSTNAME": "127.0.0.1"}
            procs.append(subprocess.Popen(["npx", "next", "start", "-p", str(fport), "-H", "127.0.0.1"], cwd=ROOT / "frontend", env=fenv,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True))
            wait_http(f"http://127.0.0.1:{fport}/login", 90)
            page = httpx.get(f"http://127.0.0.1:{fport}/login")
            check("frontend serves the HAN login page", page.status_code == 200 and "Welcome to HAN" in page.text and "Sophia" not in page.text)
            check("frontend sends security headers", "frame-ancestors 'none'" in page.headers.get("content-security-policy", ""))
            flow(f"http://127.0.0.1:{fport}", "Next.js proxy (/v1)", "The meeting is on 14 June.")
            if ui_script:
                print("\nBrowser checks")
                ui_env = {**os.environ, "HAN_URL": f"http://127.0.0.1:{fport}", "HAN_TRANSLATOR_EMAIL": "translator@example.test",
                          "HAN_TRANSLATOR_PASSWORD": translator_pw, "HAN_TECH_EMAIL": "ops@example.test", "HAN_TECH_PASSWORD": PASSWORD}
                ui = subprocess.run(["node", ui_script], env=ui_env, capture_output=True, text=True, timeout=240)
                print(ui.stdout.rstrip())
                if ui.returncode != 0:
                    print(ui.stderr.rstrip()[-1500:])
                    failures.append("browser checks")
    finally:
        for p in procs:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM) if p.args[0] == "npx" else p.terminate()
            except Exception:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()
        server.cleanup()
        shutil.rmtree(PG_DIR, ignore_errors=True)

    print("\nRESULT:", "PASS" if not failures else f"FAIL ({len(failures)} failed: {failures})")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
