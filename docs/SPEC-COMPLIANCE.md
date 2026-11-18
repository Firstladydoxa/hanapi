# Spec compliance, verification and known gaps

Maps the specification's MVP acceptance criteria (§17) and engineering checklist (Appendix B) to what exists and how it was verified.
"Verified" means an automated test or the end-to-end run exercised it in this repository. Nothing here is claimed beyond that.

## MVP acceptance criteria (§17)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Sign in; access only authorised projects | Done | `test_access_control.py` (membership, 404 for foreign projects, CSRF, logout, disabled users); browser run |
| 2 | Ask HAN to translate between a supported pair | Done | chat + `/v1/translate` tests with the labelled mock; **real MADLAD-400 3B translations verified through the gateway** by `scripts/real_engine_check.py` (en->de, en->sw, CPU) |
| 3 | Draft returned with a clear request for human review | Done | `review_required`, spec §3.2 response patterns; `test_chat_translates_with_spec_response_pattern` |
| 4 | Backend selects an eligible engine without exposing it | Done | `test_router_gateway.py`, `test_leakage.py` |
| 5 | Browser responses/client logs contain no provider identity or routing metadata | Done | leak tests over all translator endpoints incl. error paths and headers; Playwright run inspects every `/v1` response; UI leak-guard test |
| 6 | Failed provider handled gracefully, with fallback where configured | Done | fallback, timeout, malformed-output, all-fail and no-route tests |
| 7 | TM and terminology retrieval within project boundaries | Done | cross-project tests, fuzzy TM scoping test, terminology scope test |
| 8 | QA identifies number, terminology and consistency issues | Done (heuristic) | `test_platform.py` QA unit tests. Rules are basic and assert no linguistic certainty |
| 9 | Edit and save a new version without overwriting | Done | versioning tests + PostgreSQL trigger test |
| 10 | Only an authorised human can approve | Done | CSRF/membership/`can_approve` tests; no approve tool in the orchestrator; chat cannot approve |
| 11 | Approved translations enter approved TM with provenance | Done | `test_approval_records_decision_on_specific_version_and_promotes_to_tm` |
| 12 | Technical admins can inspect routing, latency, cost, errors | Done | `/v1/admin/routing-events`, `/usage`, `/health`, `/models`; Operations page |
| 13 | Automated tests for access control, provider filtering, versioning, approvals | Done | 127 backend tests + 15 frontend tests |
| 14 | Pilot can measure quality, critical errors, post-editing effort | Partly | `scripts/benchmark.py` produces a results CSV with empty reviewer columns for the §14.1 rubric. Scoring scales, thresholds, sampling and in-app feedback capture are not built |

## Engineering checklist (Appendix B)

Repository/environment config and `.env.example` ✔ · migrations ✔ (`0001_initial`, round-trip tested) · auth + server-side project permissions ✔ ·
provider adapter interface + normalised schemas ✔ · model registry + direction-specific language registry ✔ · router with eligibility, timeouts, fallback ✔ ·
translate endpoint + draft persistence ✔ · response serialiser stripping internals ✔ · "no provider identifier reaches translators" test ✔ ·
TM + terminology lookup with project scoping ✔ · QA checks with structured warnings ✔ · immutable versions + human-only approval ✔ ·
internal routing/cost/latency logs with restricted access ✔ · benchmark data and evaluation *process* ◐ (tooling only; data and rubric owners are TNI's) ·
security, privacy and model-licence reviews ✘ (must be done by TNI before real client data).

## Not exercised here (be careful)

* **Docker / Docker Compose**, including the three Dockerfiles: not run (Docker is unavailable to this build user). Only YAML-validated.
* **Celery + Redis**: jobs are tested in eager mode (`HAN_JOBS_EAGER=1`) against real PostgreSQL. The worker path and broker failure handling are untested.
* **Real engines**: **MADLAD-400 3B was run for real** (inference service + adapter + router/gateway, CPU) and verified with `scripts/real_engine_check.py`.
  Not run: the Google Cloud Translation adapter (contract-tested with mocked HTTP only), MADLAD 7B, AfriNLLB and NLLB. Translation **quality is not evaluated**:
  the §14 benchmark with TNI translators is still required before any readiness tier above Experimental. Language-code tables
  (`providers/language_codes.py`) must be verified against the live model cards. The inference service's own CI tests use a fake translator.
* **Licences**: model cards list MADLAD-400 3B as Apache-2.0, but **NLLB and AfriNLLB (both models) are CC-BY-NC-4.0 (non-commercial)** and are blocked by default.
  `license_cleared` is a legal decision; the development check records the model card as evidence only. TNI legal must confirm.
* **CPU performance**: ~90 s one-off weight load, ~7-9 s per sentence on this 40-core CPU server. Use `HAN_INFERENCE_PRELOAD` and benchmark a GPU host for production sizing.
* **pgvector / semantic TM**: the image is used in Compose, but semantic retrieval is intentionally not implemented (`memory/embeddings.py` documents the hook). Exact + fuzzy TM works on plain PostgreSQL.
* **Performance**: no load/latency tests, no backup/restore or audit-log restore verification.

## Deviations and simplifications

* Product renamed **HAN**; the spec's `sophia/` folder is the repository root, its `sophia/` package is `backend/app/han/`.
* HAN's orchestrator is **rule-based** (no language model) so behaviour is deterministic and auditable. `han/system_prompt.py` keeps Appendix A for a future LLM layer. Intent parsing covers common phrasings and asks one clarification at a time; it is not general conversation.
* Cookie sessions + CSRF (double-submit style, HMAC bound to the session) instead of bearer tokens, so the browser never holds a token script can read.
* `/v1/translate` is capped at 10,000 characters; longer text uses jobs. Jobs split paragraphs/sentences and process inline or via Celery.
* Document import (DOCX/XLIFF/XLSX) and CAT-format export are future work (§5 "later"). Export is plain text from the workspace.
* `compare_translations` compares versions of the same translation (diff). Multi-engine candidate comparison is not exposed (would risk engine identity).
* Auditor scope limiting ("limited to assigned scope") is not modelled; auditors see all audit events.
* Rate limiting is in-process (per worker). Use a shared limiter or the reverse proxy for multi-instance deployments.
* The Next.js proxy accepts requests up to the backend's 1 MB cap; the CSP allows inline scripts because Next.js requires them without a nonce setup.
* No MFA, password reset, session listing, GDPR data-subject tooling or retention-deletion jobs (`projects.retention_days` is recorded but not enforced).

## Before using real client content

Security review and dependency scanning · legal review of every model licence (record evidence in the registry) and provider terms/regions ·
data-processing agreements for any external provider · TLS and secrets management · backup/restore and retention procedures ·
translator pilot with the §14 evaluation programme before promoting any language direction beyond Experimental.
