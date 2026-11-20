# HAN: TNI AI-assisted translation platform

> **AI translates. Humans understand. TNI decides.**

HAN is the single, consistent assistant through which TNI translators request translation drafts, consult approved
terminology and Translation Memory, review and edit suggestions, and approve final work. The translation engines behind
HAN are an internal implementation detail and are never shown to translators. Built to the *TNI AI-Assisted Translation
Platform: Final Product, Technical & Implementation Specification* (its original filename is
`Sophia_TNI_Final_Developer_Specification.docx`; the document is kept outside this repository, and the product is named **HAN**).

## Repositories

| Repository | Contents |
|---|---|
| **hanapi** (this repo) | `backend/` API, `inference/` model service, `infra/` Compose, `scripts/` stack manager and checks, `docs/`, `data/` placeholders |
| **han** ([Firstladydoxa/han](https://github.com/Firstladydoxa/han)) | the Next.js frontend |

The tooling expects the frontend as a sibling folder, so after cloning this repo run:

```sh
git clone https://github.com/Firstladydoxa/han.git frontend     # ./frontend is git-ignored here
```

On the production server the two checkouts map to the subdomain web roots: `backend/` -> hanapi.tniglobal.org, `frontend/` -> han.tniglobal.org.

## What is in the box

| Path | Purpose |
|---|---|
| `backend/` | FastAPI API, orchestrator (HAN), model gateway + router, provider adapters, TM, terminology, QA, versioning/approval, audit, Celery jobs, Alembic migrations, tests |
| `frontend/` | Next.js + TypeScript + Tailwind: HAN Chat, Quick translate, Translation Workspace (CAT-style editor), admin, operations, audit |
| `inference/` | Separate model-runtime service (Transformers) used by local-model adapters. No weights are included |
| `infra/` | `docker-compose.yml` (PostgreSQL+pgvector image, Redis, migrate, backend, Celery worker, frontend, optional inference) |
| `scripts/` | `smoke_e2e.py` (full-stack smoke test), `benchmark.py` (evaluation runner) |
| `data/` | Placeholders for terminology, TM and benchmark files. Never commit client data |
| `docs/` | [Spec compliance and limitations](docs/SPEC-COMPLIANCE.md) |

## Quick start

### A. Docker Compose (target deployment)

```sh
cp .env.example .env            # replace every CHANGE_ME; add first administrator emails
docker compose -f infra/docker-compose.yml --env-file .env up --build
# frontend: http://localhost:3000   (the API is reached through the frontend's /v1 proxy)
```

The `migrate` service applies Alembic migrations and seeds languages plus the (disabled) model registry. A bootstrap
administrator without a password in `.env` gets a generated one, printed once in the `migrate` logs. **There are no default credentials.**
Terminate TLS in front of the frontend (reverse proxy) and keep `HAN_COOKIE_SECURE=1`.

> Docker is not available in the environment this repository was built in, so `docker-compose.yml` and the Dockerfiles
> have **not been executed**; they are validated only as YAML. Please run a first build on a Docker host and report issues.

### B. Local development without Docker (what the test-suite uses)

```sh
python3 -m venv ~/.han-venvs/han && ~/.han-venvs/han/bin/pip install -r backend/requirements-dev.txt
cd backend
export HAN_ENV=development HAN_ENABLE_MOCK_PROVIDER=1 HAN_JOBS_EAGER=1 \
       HAN_SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))") \
       HAN_DATABASE_URL=postgresql+psycopg://USER:PASS@localhost:5432/han     # any PostgreSQL 14+
~/.han-venvs/han/bin/alembic upgrade head
~/.han-venvs/han/bin/python -m app.seed --demo          # prints generated demo passwords ONCE
~/.han-venvs/han/bin/uvicorn app.main:app --port 8000
# second terminal
cd frontend && npm ci && HAN_BACKEND_URL=http://127.0.0.1:8000 npm run dev    # http://localhost:3000
```

No PostgreSQL server? `pip install pgserver` provides an embedded PostgreSQL 16 for development (see `scripts/smoke_e2e.py`).

> **The development mock provider** (`HAN_ENABLE_MOCK_PROVIDER=1`, refused when `HAN_ENV=production`) returns
> `[MOCK DRAFT] <your text>`. It is clearly labelled and is **not a translation**; it exists only so the automated tests and
> demos can run without a model download. To use a real engine instead, see "Running a real engine" below. In production, when nothing real is configured, HAN replies that translation is unavailable.
> It never fabricates output.

## Running a real engine (verified with MADLAD-400 3B on CPU)

HAN routes to engines through the model registry; the local-model adapters call the separate `inference/` service.
This path was verified end to end with `google/madlad400-3b-mt` (Apache-2.0 on its model card; ~12 GB download, ~12 GB RAM):

```sh
# 1. runtime in its own venv (CPU wheels shown; use a CUDA build on GPU hosts)
python3 -m venv ~/.han-venvs/inference && ~/.han-venvs/inference/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
~/.han-venvs/inference/bin/pip install transformers sentencepiece protobuf huggingface_hub fastapi "uvicorn[standard]"
# 2. weights (kept OUTSIDE the repo and web root)
HF_HOME=~/han-models/.hf ~/.han-venvs/inference/bin/python -c "from huggingface_hub import snapshot_download as d; d('google/madlad400-3b-mt', allow_patterns=['*.json','*.model','model.safetensors'])"
# 3. start the service (private network only; the token is shared with the backend)
cd inference && HF_HOME=~/han-models/.hf HF_HUB_OFFLINE=1 HAN_INFERENCE_TOKEN=<secret> HAN_INFERENCE_MODEL_MADLAD=google/madlad400-3b-mt \
  HAN_INFERENCE_PRELOAD=madlad ~/.han-venvs/inference/bin/uvicorn server:app --host 127.0.0.1 --port 9000
# 4. backend: HAN_MADLAD_URL=http://127.0.0.1:9000  HAN_INFERENCE_TOKEN=<same secret>  HAN_PROVIDER_TIMEOUT_S=120
# 5. an administrator enables the model (licence evidence, deployed, enabled), then sets language-direction readiness
```

`scripts/real_engine_check.py --url http://127.0.0.1:9000 --token-file <file with the token>` runs the whole flow against a
running inference service (nothing is fabricated before enabling; real translation; routing record visible only to admins; approval/TM).
Observed on this server (40 CPUs, no GPU): ~90 s to load the weights once, then roughly 7-9 s per sentence. That is fine for
a pilot and functional testing, not for throughput: benchmark a GPU host before sizing production.

> `license_cleared` is a **legal** decision. The script records the model card's licence as evidence in a development database only.
> TNI legal must confirm each model's licence and acceptable use before production. **NLLB and both AfriNLLB models are
> CC-BY-NC-4.0 (non-commercial) on their model cards**, so the registry ships them blocked.

## Tests and checks

```sh
cd backend  && ~/.han-venvs/han/bin/python -m pytest          # 127 tests, real PostgreSQL via pgserver
cd inference && ~/.han-venvs/han/bin/python -m pytest tests   # HTTP layer (fake translator)
cd frontend && npm run lint && npx tsc --noEmit && npm test && npm run build
~/.han-venvs/han/bin/python scripts/smoke_e2e.py --frontend   # DB + migrations + seed + API + Next.js proxy, PASS/FAIL
~/.han-venvs/han/bin/python scripts/smoke_e2e.py --ui scripts/ui_check.mjs   # + real-browser journey (needs Playwright, see script header)
```

### C. One-command local stack (single machine, real engine)

```sh
~/.han-venvs/han/bin/python scripts/han_stack.py start    # PostgreSQL + migrations + model service + backend + frontend
~/.han-venvs/han/bin/python scripts/han_stack.py status | logs [service] | stop
```

Binds to `127.0.0.1` only (frontend :3030, backend :8030, model service :9030): reach it through an SSH / VS Code port forward.
State and generated secrets live outside the web root in `~/han-data` (`credentials.txt` holds the first-run logins, mode 600).
Needs the MADLAD weights and the `inference` venv from "Running a real engine". Uses `HAN_ENV=development` (plain HTTP, no Secure cookies)
and `HAN_JOBS_BACKGROUND=1` (jobs run in a background thread of the API; use Celery + Redis for anything multi-instance). Not a production deployment.

## Production pilot on this server (cPanel / Apache)

Live at **https://han.tniglobal.org** (translators) and **https://hanapi.tniglobal.org** (API). Verified over the real URLs with
valid Let's Encrypt certificates (cPanel AutoSSL).

```
Browser -> Apache (TLS) -> .htaccess reverse proxy -> Next.js :3030 --(/v1 proxy, loopback)--> FastAPI :8030 -> model service :9030
                                                                                              \-> PostgreSQL (private unix socket)
```

* Each subdomain's folder (`frontend/`, `backend/`) is its web root, but its `.htaccess` proxies **every** request to the app (except
  `/.well-known/` for AutoSSL), so no source file is downloadable. `hanapi` exposes only `/v1/*` and `/healthz`; API docs are off.
  cPanel's own PHP-handler block in those files is preserved. If either `.htaccess` is replaced, restore the rewrite rules.
* The browser uses same-origin `https://han.tniglobal.org/v1/...`; the frontend proxies to the backend over loopback. That keeps the
  session cookie first-party (`HttpOnly; Secure; SameSite=Lax`) and CORS closed. `hanapi` is the same backend, reachable for tools/admin.
* All HAN services listen on `127.0.0.1` only. HAN's PostgreSQL has no TCP port (unix socket). (Port 5432 on this server belongs to a
  different system PostgreSQL.)
* Runs with `HAN_ENV=production` (strict startup checks, Secure cookies, no mock engine, no OpenAPI). Behind the proxy the client IP
  used for rate limiting and audit is the **last** `X-Forwarded-For` entry (the one Apache appended); client-supplied entries are ignored.

```sh
S="$HOME/.han-venvs/han/bin/python scripts/han_stack.py --profile prod"
$S status | logs [service] | stop | start      # start is idempotent; the model needs 1-3 minutes to load
$S build                                       # rebuild the frontend after code changes, then: stop && start
$S manage add-users --project "TNI Translator Pilot" --role translator name@example.org   # prints a generated password once
$S manage reset-password name@example.org
$S backup                                      # pg_dump -> ~/han-data-prod/backups (14 kept); also runs daily 03:15
```

`install-cron` (already applied) adds a per-minute `ensure` that restarts anything that died or hung (and starts everything at boot),
plus the daily backup; your other crontab entries are preserved. State and secrets live in **`~/han-data-prod`** (mode 700, outside the
web root): `credentials.txt` holds the generated administrator, 10 pilot-translator (`pilot01..10@tniglobal.org`) and reviewer logins.
The dev stack (`--profile dev`, `~/han-data`) uses the same ports; stop one before starting the other.

Pilot content: project **TNI Translator Pilot**, pairs English <-> German, French, Spanish, Swahili, all **Experimental** (HAN labels
every draft accordingly). Promote a pair in *Administration -> Language readiness* only after TNI translators have evaluated it.

**Know the limits:** one CPU-only model process, so requests queue (about 3-11 s per sentence; a larger request or a busy server takes
longer; the first request after a restart is slower). Quick translate is capped at 4,000 characters (longer text: Translation Workspace
jobs, which run in a background thread of the API). No MFA or self-service password reset. Backups are written but a restore has not
been drilled (`pg_restore -h ~/han-data-prod/pg -U postgres -d postgres --clean <dump>`). The model's licence was recorded from its model
card by a development check: **TNI legal must confirm before client content is used.** Translation text is processed locally only; no
external provider is configured.

## How it works

```
Translator -> Next.js app (/v1 proxy) -> FastAPI (auth, CSRF, RBAC, response whitelisting)
   -> HAN orchestrator -> project context | Translation Memory | Terminology | QA | Versioning & approval
   -> Model gateway/router (internal) -> provider adapters (cloud API, local inference service)
   -> Draft -> QA -> Translator review -> HUMAN approval -> approved TM (with provenance)
```

* **One identity.** Translators see HAN only. Public schemas (`models/schemas.py`) are whitelists; internal routing types
  live in `models/internal_schemas.py` and the admin router. A safety-net middleware blocks any translator-facing JSON that
  carries registry identifiers or routing keys (fail-closed), and a test proves it.
* **Human authority.** HAN has no approval tool. Approval needs a signed-in human session, a CSRF token and a project
  member whose role allows it. The approval attaches to one immutable version and only then enters the approved TM.
* **Immutable history.** Edits insert new versions (parent-linked). PostgreSQL triggers reject UPDATE/DELETE on
  `translation_versions` and `approvals`. Editing an approved version creates a new, unapproved version.
* **Model-agnostic routing.** The router uses the registry, direction readiness, benchmark scores, health, latency,
  cost, licence clearance, data policy and context limits; the gateway adds timeouts, bounded retries and invisible fallback.
* **Language readiness tiers** (per direction): `production`, `assisted`, `experimental` (only for pilot-opt-in
  projects), `unsupported` (no automation; translators get an escalation message). Any direction not defined is unsupported.
* **Licence gate.** A model is routable only if enabled, deployed and `license_cleared`. Clearing requires recorded
  licence evidence. The NLLB and AfriNLLB rows ship **uncleared** (CC-BY-NC non-commercial licences).
* **Data policy.** External processors (the cloud API) are used only for projects with *allow external processing*.
* **Privacy.** Logs record lengths and hashes, not translation text (content logging is off and refused in production).
  Every access denial, edit, approval and admin change is written to the audit trail.

### Roles

| Role | Sees |
|---|---|
| Translator / reviewer / project manager | Their projects' content and workflow; no engine identity |
| TNI administrator | Users, projects, members, terminology, language readiness; engine details only if explicitly granted |
| Technical administrator | Model registry, routing events, usage/cost/latency, health |
| Auditor | Audit events |

### Enabling real translation (administrators)

1. Set provider environment variables (`HAN_GOOGLE_API_KEY` and/or `HAN_MADLAD_URL`, …). Obtain **legal and security approval** first.
2. In *Operations → models* (API `PATCH /v1/admin/models/{key}`): record licence evidence, set `license_cleared`, `deployment_status=deployed`, `enabled=true`.
3. In *Administration → Language readiness*: set a tier per direction **after** evaluating it with TNI translators.
4. For external providers, switch on *allow external processing* for the specific project.

## Conversations, knowledge base and language expansion

See [docs/HAN-INTELLIGENCE-UPGRADE.md](docs/HAN-INTELLIGENCE-UPGRADE.md) (audit, 6-7 pairs root cause, assistant, knowledge governance, limits, deploy and rollback).

## Configuration

See `.env.example` (placeholders only). Production refuses to start with a missing/short `HAN_SECRET_KEY`.

## Not production-ready: read before real client data

See [docs/SPEC-COMPLIANCE.md](docs/SPEC-COMPLIANCE.md). Highlights: Docker artefacts and Celery-with-Redis were not run;
the Google cloud adapter was never contacted and no translation quality evaluation has been done (the local MADLAD path was run for real); rate limiting is per-process; no MFA/password recovery;
no document import/export beyond plain text; no formal security review, load test or backup/restore drill; model licences
and provider data-processing terms must be verified by legal before use.


## Rhapsody of Realities module

The Rhapsody publication workflow is a native HAN API domain under `/v1/rhapsody` (reuses HAN auth, CSRF, roles, languages, PostgreSQL and audit). Apply Alembic migrations through `0009_rhapsody_drafting`. Set `HAN_RHAPSODY_STORAGE_DIR` to a persistent private volume outside the web root.

- **Layout:** an administrator uploads the monthly English DOCX (and, only if it changed, the InDesign XLIFF template) and tells HAN, e.g. “Han, start the layout of Rhapsody for the month of November 2026 using the word document I uploaded”. HAN recognises the 30/31 articles (weekday/date checked), reuses the cover and introduction from the previous master with the month/year updated, builds the master, and the administrator reviews and activates it. URLs, e-mails and Bible-version codes are locked and not translated.
- **Translation:** a translator says “Han, start the translation of Rhapsody in French for the month of November” (or uses the Rhapsody page). HAN drafts each paragraph in order of authority: approved TNI glossary, translation memory, then the model, protecting layout tags. Drafts are labelled `ai` and must be confirmed or edited before submission; proofreaders approve or request changes; the result can be exported to DOCX or printed to PDF.
- **Not yet done:** theological retrieval during drafting, translation-memory feeding from approved issues, InDesign-compatible export and native PDF generation.


## Email authentication and registration recovery

HAN supports self-registration for translator accounts, mandatory email verification, password reset by six-digit email code, and recovery reminders for incomplete registrations. Codes are stored only as keyed hashes, expire after 15 minutes by default, are single-use, are invalidated when a replacement is issued, and are limited to five attempts. Resends have a 60-second cooldown; an unverified user who correctly enters their password at sign-in is automatically sent a fresh verification code and directed to the verification screen. Password reset revokes all existing sessions.

Configure Brevo server-side (never in the browser): `HAN_SMTP_HOST`, `HAN_SMTP_PORT` (587, STARTTLS), `HAN_SMTP_USERNAME`, `HAN_SMTP_PASSWORD`, `HAN_MAIL_FROM_ADDRESS`, `HAN_MAIL_FROM_NAME`, `HAN_PUBLIC_APP_URL`, and a unique random `HAN_EMAIL_AUTH_PEPPER` of at least 32 characters. The production startup check requires the SMTP credentials and the pepper. Apply migrations with `alembic upgrade head`.

Incomplete-registration reminders are durable and scheduled in the database. Run `python -m app.send_registration_reminders` from the `backend/` directory every five minutes using cron or a systemd timer. The reminder contains a signed, seven-day recovery link; opening it requests a fresh six-digit code. The reminder runner is intentionally a separate scheduled process rather than an in-process timer, so it works across restarts and multiple API workers. Configure monitoring for this scheduled command and Brevo delivery failures.
