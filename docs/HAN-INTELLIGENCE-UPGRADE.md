# HAN intelligence and language expansion upgrade

Implements `writing-block.md`. This document records what changed, what was measured, and what is still **not** done.

## 1. MADLAD audit (Stage 1: technical)

Evidence: `docs/reports/madlad-audit/probe-results.json` (418 languages, one sentence each, English to X and back) and `scripts/language_audit.py` (re-runnable, resumable).

| Fact | Finding |
|---|---|
| Checkpoint | `google/madlad400-3b-mt`, revision `fa184c67…`. This is the **3B** model (2.94B parameters), not a 7B model. |
| Language tokens | 419 plain `<2xx>` tokens, 42 variant tokens and 31 control tokens in the tokenizer vocabulary. |
| Prompt format | `<2xx> text`; only the **target** is specified. The source language is detected by the model. |
| Probe result | 348 passed, 70 degraded (the output echoes the input or loops), 0 failed. |
| Code quirks | `iw` is not a token (Hebrew is `he`); `tl` is absent (use `fil`); `nb` and `jw` are absent (use `no` and `jv`). Aliases are mapped in `backend/app/data/madlad_languages.json`. |

**A technical pass is not a quality judgement.** A single sentence and a round-trip similarity score are noisy. Stage 2 (human evaluation by qualified translators) has **not** been done.

## 2. Why only 6 to 7 language pairs were offered

1. `providers/language_codes.py` held a hand-written list of 50 codes instead of the model's real vocabulary.
2. The seed created directions only for English with de, fr, es and sw.
3. The frontend offered only those pairs.

The limit was in HAN's configuration, not in the model.

**Removed:** the hand-written list and the per-code exception table. **Retained:** the readiness tiers, project gating and the rule that nothing becomes Production automatically.

## 3. Language registry and enablement

- `languages` (native name, script, model codes, reviewed flag) holds 419 languages; `language_directions` has the tier plus **independent** `technical_status` and `validation_status`.
- Tiers: unsupported, experimental, assisted, production. Availability labels shown to users: Available, Available with review, Controlled testing, Not yet enabled.
- `python -m app.seed --expand-languages` imports probe evidence (as *unsupported*) and opens the curated, technically passing English pairs as **Experimental** (controlled testing). Experimental directions are visible only to projects with `pilot_opt_in`.
- Administration → Language readiness: filter, per-direction technical test, validation status, tier changes, and a bulk "enable verified languages for controlled testing" action. A test never enables a direction.
- Engine tokens are visible only at `GET /v1/admin/models/language-codes` (engine-protected); translators never see engine identity.

## 4. Conversational HAN

- **Assistant service** (`inference/assistant.py`, port 9031, private, bearer token): Qwen2.5-1.5B-Instruct Q4_K_M via llama.cpp for chat, multilingual-e5-small for embeddings. If it is down, HAN replies with varied deterministic fallbacks; translation is unaffected.
- **Intelligence layer** (`backend/app/han/intelligence.py`): intent routing. Language support answers come straight from the registry. Terminology answers come only from approved terms. TNI and platform questions are answered **only from approved knowledge**; with no source HAN says it has no approved information and does not call the model.
- **Quality guards** (`han/quality.py`): removes reasoning tags, generic openers, vendor/engine names and approval claims; blocks invented policy when ungrounded; avoids repeated replies; trims truncation.
- The existing translate flow, engine deflection and "HAN never approves" rules are unchanged.

## 5. Knowledge base (RAG)

- Admin only (TNI and technical administrators): `/v1/admin/knowledge/...` and Administration → Knowledge base. Upload `.txt .md .docx .pdf` (5 MB) or paste text.
- Governance: documents are drafts until a **version is approved**; only the approved version is chunked and searchable. Deactivating removes it. Metadata: category, languages, audience roles, optional project. The built-in "Using HAN" guide is system-managed.
- Retrieval: keyword (Postgres full text) plus semantic (pgvector), filtered by status, project, audience role and language. Answers show their sources to the translator.
- Maintenance: `python -m app.manage seed-knowledge | reindex-knowledge | purge-conversations`.

## 6. Conversations

- `POST/GET /v1/conversations`, `GET/PATCH/DELETE /v1/conversations/{id}`, `GET .../messages?before_seq=`, `POST .../messages`.
- Strictly per user (other users and admins get 404). Greeting stored once as message 1 (personalised from the first name; anonymous if the name looks unusable). Titles, running summaries, search, archive, soft delete and a 30 day purge (daily, in the backup job).
- `POST /v1/chat` remains for compatibility and now stores history too.
- "Ask HAN about this" shares exactly one translation, and only if the user could open it.

## 7. Known limits (please read)

- The chat model is **small** (1.5B). It can be vague or wrong; that is why policy and terminology are grounded or declined rather than generated.
- MADLAD is the 3B model. 70 languages are technically degraded. No language beyond the original four has human validation.
- Keyword retrieval requires at least two matching meaningful words; the semantic path needs the assistant service.
- Experimental drafts must be reviewed carefully; HAN labels them as such.

## 8. Deploy and rollback

Deploy (production profile): `scripts/han_stack.py --profile prod backup`, install new requirements into the HAN venv, `alembic upgrade head`, `python -m app.seed --expand-languages`, then `han_stack.py --profile prod build` and `ensure`.
Rollback: restore the latest `~/han-data-prod/backups/han-*.dump`, check out the previous tag and rebuild. Migrations 0002 to 0004 are additive.
