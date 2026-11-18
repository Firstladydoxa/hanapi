"""QA rules (unit, DB-free), chat intents/orchestration, jobs, knowledge endpoints, migrations, config safety."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.database import SessionLocal, get_engine
from app.models.db import Language, ProjectMember, TerminologyEntry
from app.qa import QAContext
from app.qa.runner import run_rules
from tests.conftest import alembic_config, translate


def ctx(src, tgt, terms=(), prior=(), script=None, sl="en", tl="de"):
    return QAContext(source_text=src, target_text=tgt, source_language=sl, target_language=tl, target_script=script, terms=list(terms),
                     prior_translations=list(prior))


def kinds(ws):
    return [w["type"] for w in ws]


def term(src, tgt, forbidden=()):
    return SimpleNamespace(source_term=src, target_term=tgt, forbidden_alternatives=list(forbidden), usage_note=None)


# ------------------------------------------------------------------ QA rules
def test_number_rule():
    assert "number" not in kinds(run_rules(ctx("Pay 1,200.50 EUR by 12 May.", "Zahlen Sie bis 12 Mai 1,200.50 EUR.")))
    ws = run_rules(ctx("Pay 1,200 EUR by 12 May.", "Zahlen Sie 1,300 EUR bis 12 Mai."))
    assert "number" in kinds(ws)
    assert "number" in kinds(run_rules(ctx("Room 101", "Zimmer")))


def test_terminology_rule_missing_and_forbidden():
    t = term("invoice", "Rechnung", forbidden=["Faktura"])
    assert "terminology" not in kinds(run_rules(ctx("Send the invoice.", "Senden Sie die Rechnung.", [t])))
    assert "terminology" in kinds(run_rules(ctx("Send the invoice.", "Senden Sie die Zahlung.", [t])))
    ws = run_rules(ctx("Send the invoice.", "Senden Sie die Rechnung und Faktura.", [t]))
    assert any(w["type"] == "terminology" and "Faktura" in w["message"] for w in ws)


def test_name_rule_flags_dropped_proper_names():
    assert "name" in kinds(run_rules(ctx("Please contact Amara Okafor today.", "Bitte kontaktieren Sie heute.")))
    assert "name" not in kinds(run_rules(ctx("Please contact Amara Okafor today.", "Bitte kontaktieren Sie Amara Okafor heute.")))
    assert "name" not in kinds(run_rules(ctx("The meeting is on 12 May, a Monday.", "Das Treffen ist am 12. Mai, einem Montag.", sl="en", tl="es"))), "months/weekdays are translated"


def test_consistency_and_repetition_rules():
    assert "consistency" in kinds(run_rules(ctx("Hello there", "Hallo da da", [])))
    prior = [SimpleNamespace(target_text="Guten Tag", source_text="Hello there")]
    assert "consistency" in kinds(run_rules(ctx("Hello there", "Hallo", prior=prior)))
    assert "consistency" not in kinds(run_rules(ctx("Hello there", "Guten Tag", prior=prior)))


def test_formatting_rule_placeholders_tags_and_whitespace():
    assert "format" in kinds(run_rules(ctx("Hello {name}", "Hallo")))
    assert "format" in kinds(run_rules(ctx("Click <b>here</b>", "Klicken Sie hier")))
    assert "format" in kinds(run_rules(ctx("Hello.", "Hallo")))
    assert "format" not in kinds(run_rules(ctx("Hello {name}.", "Hallo {name}.")))


def test_qa_messages_never_claim_certainty():
    for w in run_rules(ctx("Pay 5 EUR to Amara Okafor", "Zahlen Sie")):
        assert "wrong" not in w["message"].lower() and "incorrect" not in w["message"].lower()
        assert w["severity"] in ("info", "warning")


# ------------------------------------------------------------------ knowledge endpoints
def add_term(world, **kw):
    with SessionLocal() as db:
        d = dict(project_id=world.projects["p1"].id, scope="project", source_language="en", target_language="de", source_term="invoice",
                 target_term="Rechnung", status="approved", forbidden_alternatives=["Faktura"], domain="legal")
        d.update(kw)
        db.add(TerminologyEntry(**d))
        db.commit()


def test_terminology_search_scoping_and_status(login, world):
    add_term(world)
    add_term(world, source_term="draftterm", target_term="x", status="draft")
    add_term(world, project_id=world.projects["p2"].id, source_term="secret", target_term="geheim")
    add_term(world, project_id=None, scope="global", source_term="global-term", target_term="Globalbegriff")
    alice = login("alice")
    q = {"project_id": str(world.projects["p1"].id), "source_language": "en", "target_language": "de"}
    found = {t["source_term"] for t in alice.get("/v1/terminology/search", params=q).json()["results"]}
    assert found == {"invoice", "global-term"}, "own approved + global only; no drafts, no other project"
    assert alice.get("/v1/terminology/search", params={**q, "q": "inv"}).json()["results"][0]["forbidden"] == ["Faktura"]


def test_translate_returns_terminology_and_qa_warnings(login, world):
    add_term(world)
    r = translate(login("alice"), world.projects["p1"], "Send the invoice on 12 May.").json()
    assert [t["source_term"] for t in r["terminology"]] == ["invoice"]
    assert r["review_required"] is True and r["status"] == "draft"
    assert {w["type"] for w in r["warnings"]} >= {"readiness", "terminology"}, "assisted tier + mock output lacks preferred term"
    assert r["review_note"] and "review" in r["review_note"].lower()


def test_qa_check_endpoint(login, world):
    r = login("alice").post("/v1/qa/check", {"project_id": str(world.projects["p1"].id), "source_text": "Pay 5 EUR", "target_text": "Zahlen Sie 6 EUR",
                                             "source_language": "en", "target_language": "de"})
    assert r.status_code == 200 and "number" in {w["type"] for w in r.json()["warnings"]}


def test_validation_rejects_bad_input_without_echoing_it(login, world):
    alice = login("alice")
    pid = str(world.projects["p1"].id)
    r = alice.post("/v1/translate", {"project_id": pid, "source_language": "english!!", "target_language": "de", "text": "SECRET CONTENT"})
    assert r.status_code == 422 and "SECRET CONTENT" not in r.text
    assert alice.post("/v1/translate", {"project_id": pid, "source_language": "en", "target_language": "de", "text": ""}).status_code == 422
    assert alice.post("/v1/translate", {"project_id": pid, "source_language": "en", "target_language": "en", "text": "x"}).status_code == 422
    assert alice.post("/v1/translate", {"project_id": pid, "source_language": "en", "target_language": "de", "text": "x", "extra": 1}).status_code == 422
    big = alice.post("/v1/translate", {"project_id": pid, "source_language": "en", "target_language": "de", "text": "x" * 10_001})
    assert big.status_code == 422 and big.json()["detail"]["code"] == "text_too_long"
    assert alice.client.post("/v1/translate", content=b"x" * 1_100_000, headers={"X-CSRF-Token": alice.csrf, "content-type": "application/json"}).status_code == 413


def test_translate_rate_limit(login, world, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_translate_per_min", 2)
    alice = login("alice")
    codes = [translate(alice, world.projects["p1"]).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


# ------------------------------------------------------------------ chat
def chat(sess, world, message, cid=None, **kw):
    body = {"project_id": str(world.projects["p1"].id), "message": message, **kw}
    if cid:
        body["conversation_id"] = cid
    r = sess.post("/v1/chat", body)
    assert r.status_code == 200, r.text
    return r.json()


def test_chat_translates_with_spec_response_pattern(login, world):
    alice = login("alice")
    r = chat(alice, world, "Translate this text from English to German: Good morning, team.")
    assert r["translation"]["source_language"] == "en" and r["translation"]["target_language"] == "de"
    assert r["translation"]["source_text"] == "Good morning, team."
    assert r["reply"].startswith("Here is my suggested translation:\n\n") and r["reply"].rstrip().endswith("Please review it and make any corrections before approving it.")
    assert r["actions"] == [{"type": "open_in_workspace", "translation_id": r["translation"]["translation_id"]}]


@pytest.mark.parametrize("msg", [
    'Translate "Good morning" from English to German',
    "english to german: Good morning",
    "Translate Good morning from English into German.",
    "Please translate to German from English: Good morning",
    "translate from en to de: Good morning",
])
def test_chat_understands_common_phrasings(login, world, msg):
    r = chat(login("alice"), world, msg)
    assert r["translation"] and r["translation"]["target_language"] == "de" and r["translation"]["source_text"] == "Good morning", msg


def test_chat_asks_one_question_at_a_time_and_remembers(login, world):
    alice = login("alice")
    r = chat(alice, world, "Translate this into German")
    assert r["clarification"]["field"] == "text" and r["reply"] == "What text would you like me to translate?"
    r = chat(alice, world, "Thank you very much", r["conversation_id"])
    assert r["clarification"]["field"] == "source_language"
    r = chat(alice, world, "English", r["conversation_id"])
    assert r["translation"]["source_text"] == "Thank you very much" and r["translation"]["target_language"] == "de"


def test_chat_missing_target_language(login, world):
    r = chat(login("alice"), world, 'Translate "Hello" from English')
    assert r["clarification"]["field"] == "target_language" and "into" in r["reply"]


def test_chat_deflects_engine_questions_politely(login, world):
    for msg in ("Which engine did you use?", "What model powers you?", "Are you ChatGPT or Google Translate?", "which provider translated this"):
        r = chat(login("alice"), world, msg)
        assert "HAN manages the translation process" in r["reply"] and r["translation"] is None
        low = r["reply"].lower()
        assert not any(w in low for w in ("madlad", "nllb", "google", "gpt-", "openai"))


def test_chat_unsupported_pair_and_unavailable(login, world):
    r = chat(login("alice"), world, "Translate hello from English to Swahili")
    assert "can't offer an automated draft" in r["reply"] and r["translation"] is None
    with SessionLocal() as db:
        from app.models.db import ModelRegistry

        db.get(ModelRegistry, "dev-mock").enabled = False
        db.commit()
    r = chat(login("alice"), world, "Translate hello from English to German")
    assert r["reply"] == "I'm sorry, I couldn't complete the translation at the moment. Please try again shortly."


def test_chat_greeting_and_conversation_isolation(login, world):
    alice, rita = login("alice"), login("rita")
    cid = chat(alice, world, "hello")["conversation_id"]
    assert chat(alice, world, "hello", cid)["reply"].strip()
    r = rita.post("/v1/chat", {"project_id": str(world.projects["p1"].id), "message": "hi", "conversation_id": cid})
    assert r.status_code == 404, "another user's conversation is not accessible"


# ------------------------------------------------------------------ jobs
def make_job(sess, world, text, **kw):
    return sess.post("/v1/translation-jobs", {"project_id": str(world.projects["p1"].id), "source_language": "en", "target_language": "de", "text": text, **kw})


def test_job_segments_and_progress(login, world):
    alice = login("alice")
    r = make_job(alice, world, "First paragraph.\n\nSecond paragraph.\n\nThird.", title="Doc")
    assert r.status_code == 201 and r.json()["segment_count"] == 3 and r.json()["status"] == "ready"
    job = alice.get(f"/v1/translation-jobs/{r.json()['job_id']}").json()
    assert [s["status"] for s in job["segments"]] == ["draft"] * 3 and job["progress"] == {"total": 3, "done": 3, "approved": 0}
    seg = job["segments"][0]
    assert seg["current_version"]["origin"] == "ai" and seg["source_text"] == "First paragraph."
    a = alice.post(f"/v1/versions/{seg['current_version']['version_id']}/approve", {"decision": "approved"})
    assert a.status_code == 201
    job = alice.get(f"/v1/translation-jobs/{r.json()['job_id']}").json()
    assert job["progress"]["approved"] == 1 and job["segments"][0]["status"] == "approved"
    assert alice.get("/v1/translation-jobs", params={"project_id": str(world.projects["p1"].id)}).json()[0]["title"] == "Doc"


def test_background_job_mode_returns_immediately_and_completes(login, world, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "jobs_eager", False)
    monkeypatch.setattr(get_settings(), "jobs_background", True)
    alice = login("alice")
    r = make_job(alice, world, "One.\n\nTwo.")
    assert r.status_code == 201 and r.json()["status"] in ("queued", "processing", "ready")
    import time

    for _ in range(50):
        job = alice.get(f"/v1/translation-jobs/{r.json()['job_id']}").json()
        if job["status"] == "ready":
            break
        time.sleep(0.2)
    assert job["status"] == "ready" and [s["status"] for s in job["segments"]] == ["draft", "draft"]


def test_job_partial_failure_marks_segments_needs_attention(login, world):
    from app.models import registry as reg
    from tests.test_router_gateway import Fake, add_model, disable_mock

    disable_mock()

    class Flaky(Fake):
        def _translate(self, req):
            if "BAD" in req.text:
                from app.providers.base import ProviderError

                raise ProviderError("malformed", "x")
            return f"ok:{req.text}", {}

    add_model("flaky", Flaky("f"))
    alice = login("alice")
    r = make_job(alice, world, "Fine one.\n\nBAD two.\n\nFine three.")
    assert r.json()["status"] == "partial"
    statuses = [s["status"] for s in alice.get(f"/v1/translation-jobs/{r.json()['job_id']}").json()["segments"]]
    assert statuses == ["draft", "needs_attention", "draft"]


def test_job_validation_and_visibility(login, world):
    alice, rita = login("alice"), login("rita")
    assert make_job(alice, world, "").status_code in (422,)
    assert alice.post("/v1/translation-jobs", {"project_id": str(world.projects["p1"].id), "source_language": "en", "target_language": "de"}).status_code == 422
    assert make_job(alice, world, "x\n\n" * 600).json()["detail"]["code"] == "job_too_large"
    jid = make_job(alice, world, "Hello.").json()["job_id"]
    assert rita.get(f"/v1/translation-jobs/{jid}").status_code == 200, "reviewer sees project jobs"
    with SessionLocal() as db:
        db.add(ProjectMember(project_id=world.projects["p1"].id, user_id=world.users["bob"].id, role="translator", can_approve=True))
        db.commit()
    assert login("bob").get(f"/v1/translation-jobs/{jid}").status_code == 404, "another translator's job is hidden"
    assert make_job(alice, world, "Hi", **{}).status_code == 201
    assert alice.post("/v1/translation-jobs", {"project_id": str(world.projects["p1"].id), "source_language": "en", "target_language": "sw", "text": "x"}).status_code == 422


def test_text_splitter():
    from app.services import split_text

    assert split_text("A.\n\nB.") == ["A.", "B."]
    long = " ".join(["Sentence number %d is here." % i for i in range(100)])
    parts = split_text(long, 200)
    assert all(len(p) <= 200 for p in parts) and " ".join(parts).split() == long.split()
    assert split_text("x" * 2500, 1000) == ["x" * 1000, "x" * 1000, "x" * 500]
    assert split_text("   \n\n  ") == []


# ------------------------------------------------------------------ admin
def test_admin_project_member_and_readiness_management(login, world):
    tina = login("tina")
    r = tina.post("/v1/admin/projects", {"name": "New", "domain": "tech", "pilot_opt_in": True})
    assert r.status_code == 201
    pid = r.json()["id"]
    uid = str(world.users["bob"].id)
    m = tina.put(f"/v1/admin/projects/{pid}/members", {"members": [{"user_id": uid, "role": "translator"}]})
    assert m.status_code == 200 and m.json()[0]["can_approve"] is True
    assert [p["name"] for p in login("bob").get("/v1/projects").json()] == ["Project Two", "New"] or {p["name"] for p in login("bob").get("/v1/projects").json()} == {"Project Two", "New"}
    d = tina.put("/v1/admin/language-directions", {"directions": [{"source_code": "en", "target_code": "sw", "readiness_tier": "assisted", "review_note": "pilot data"}]})
    assert d.status_code == 200
    assert translate(login("bob"), type("P", (), {"id": pid}), "Hello", source="en", target="sw").status_code == 201
    assert tina.put("/v1/admin/language-directions", {"directions": [{"source_code": "en", "target_code": "qq", "readiness_tier": "assisted"}]}).status_code == 422
    assert tina.patch(f"/v1/admin/projects/{pid}", {"directions": [{"source_code": "en", "target_code": "de"}]}).status_code == 200
    assert translate(login("bob"), type("P", (), {"id": pid}), "Hello", source="en", target="sw").status_code == 422, "project direction restriction"


def test_terminology_admin_flow_records_history(login, world):
    tina = login("tina")
    body = {"project_id": str(world.projects["p1"].id), "scope": "project", "source_language": "en", "target_language": "de", "source_term": "contract",
            "target_term": "Vertrag", "forbidden": ["Kontrakt"]}
    r = tina.post("/v1/admin/terminology", body)
    assert r.status_code == 201 and r.json()["status"] == "draft"
    tid = r.json()["term_id"]
    q = {"project_id": str(world.projects["p1"].id), "source_language": "en", "target_language": "de"}
    assert login("alice").get("/v1/terminology/search", params=q).json()["results"] == []
    assert tina.patch(f"/v1/admin/terminology/{tid}", {"status": "approved", "comment": "approved by lead"}).status_code == 200
    assert [t["source_term"] for t in login("alice").get("/v1/terminology/search", params=q).json()["results"]] == ["contract"]
    with SessionLocal() as db:
        from app.models.db import TerminologyApproval

        assert [(h.from_status, h.to_status) for h in db.query(TerminologyApproval).order_by(TerminologyApproval.created_at)] == [(None, "draft"), ("draft", "approved")]
    assert tina.post("/v1/admin/terminology", {**body, "scope": "global"}).status_code == 422


# ------------------------------------------------------------------ migrations / config
def test_migration_downgrade_and_upgrade_roundtrip():
    from alembic import command

    cfg = alembic_config()
    command.downgrade(cfg, "base")
    with get_engine().connect() as conn:
        assert conn.execute(text("select count(*) from pg_tables where schemaname='public' and tablename='translation_versions'")).scalar() == 0
        assert conn.execute(text("select count(*) from pg_proc where proname='han_forbid_mutation'")).scalar() == 0
    command.upgrade(cfg, "head")
    with get_engine().connect() as conn:
        assert conn.execute(text("select count(*) from pg_trigger where tgname in ('translation_versions_immutable','approvals_immutable')")).scalar() == 2


def test_production_refuses_insecure_configuration():
    from app.config import INSECURE_DEFAULT_SECRET, Settings

    with pytest.raises(RuntimeError):
        Settings(env="production", secret_key=INSECURE_DEFAULT_SECRET).validate_for_startup()
    with pytest.raises(RuntimeError):
        Settings(env="production", secret_key="short").validate_for_startup()
    with pytest.raises(RuntimeError):
        Settings(env="production", secret_key="x" * 40, content_logging=True).validate_for_startup()
    Settings(env="production", secret_key="x" * 40).validate_for_startup()


def test_seed_is_idempotent_and_has_no_default_credentials(monkeypatch, capsys):
    from app import seed

    monkeypatch.setenv("HAN_BOOTSTRAP_TECH_ADMIN_EMAIL", "ops@example.test")
    monkeypatch.delenv("HAN_BOOTSTRAP_TECH_ADMIN_PASSWORD", raising=False)
    assert seed.main(["--demo"]) == 0
    out = capsys.readouterr().out
    assert "generated password (shown once)" in out and "ops@example.test" in out
    assert seed.main(["--demo"]) == 0
    assert capsys.readouterr().out.count("generated password") == 0, "passwords are shown only once"
    with SessionLocal() as db:
        from app.models.db import User

        assert db.query(User).filter_by(email="ops@example.test").one().role == "technical_admin"
        assert db.query(Language).count() >= 20


def test_client_ip_uses_the_proxy_observed_address_only(monkeypatch):
    from starlette.requests import Request

    from app.config import get_settings
    from app.deps import client_ip

    def req(xff):
        headers = [(b"x-forwarded-for", xff.encode())] if xff else []
        return Request({"type": "http", "headers": headers, "client": ("10.0.0.9", 1234)})

    monkeypatch.setattr(get_settings(), "trust_proxy", True)
    assert client_ip(req("6.6.6.6, 203.0.113.7")) == "203.0.113.7", "client-supplied prefix is ignored"
    assert client_ip(req("203.0.113.7")) == "203.0.113.7"
    assert client_ip(req(None)) == "10.0.0.9"
    monkeypatch.setattr(get_settings(), "trust_proxy", False)
    assert client_ip(req("6.6.6.6, 203.0.113.7")) == "10.0.0.9", "header ignored unless a trusted proxy is configured"


def test_pilot_seed_and_account_cli(capsys):
    from app import manage, seed
    from tests.conftest import Session

    with SessionLocal() as db:
        assert seed.seed_pilot(db) == [f"project created: {seed.PILOT_PROJECT}"]
        assert seed.seed_pilot(db) == [f"project exists: {seed.PILOT_PROJECT}"]
    assert manage.main(["add-users", "--project", seed.PILOT_PROJECT, "--role", "translator", "Pilot.One@example.test"]) == 0
    line = capsys.readouterr().out.strip()
    email, password = line.split()
    assert email == "pilot.one@example.test" and len(password) >= 16
    sess = Session().login(email, password)
    projects = sess.get("/v1/projects").json()
    assert [p["name"] for p in projects] == [seed.PILOT_PROJECT]
    detail = sess.get(f"/v1/projects/{projects[0]['id']}").json()
    tiers = {d["readiness_tier"] for d in detail["language_directions"]}
    assert tiers == {"experimental"} and detail["can_approve"] is True, "pilot pairs are honestly labelled experimental"
    assert manage.main(["add-users", "--project", seed.PILOT_PROJECT, "pilot.one@example.test"]) == 0
    assert "password unchanged" in capsys.readouterr().out
    assert manage.main(["reset-password", "pilot.one@example.test"]) == 0
    new_pw = capsys.readouterr().out.split()[1]
    assert new_pw != password and Session().login(email, new_pw)
    assert manage.main(["add-users", "--project", "No such project", "x@example.test"]) == 2


def test_request_id_header_and_security_headers(login, world, anon):
    r = anon.client.get("/healthz", headers={"X-Request-ID": "abcdefgh12345678"})
    assert r.headers["x-request-id"] == "abcdefgh12345678" and r.headers["x-content-type-options"] == "nosniff"
    assert anon.client.get("/healthz", headers={"X-Request-ID": "bad id!"}).headers["x-request-id"] != "bad id!"
