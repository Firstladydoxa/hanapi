"""Persistent conversations, knowledge governance and the conversational layer's guards."""
from __future__ import annotations

import json

from app.han import assistant_client


def _new(sess, world, **kw):
    r = sess.post("/v1/conversations", {"project_id": str(world.projects["p1"].id), **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _say(sess, cid, text, **kw):
    r = sess.post(f"/v1/conversations/{cid}/messages", {"message": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _kb(admin, title="Turnaround policy", text="# Turnaround\nAll TNI Swahili translations must be returned within five working days.", **kw):
    r = admin.post("/v1/admin/knowledge/documents", {"title": title, "category": "guidelines", "text": text, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _approve(admin, doc):
    r = admin.post(f"/v1/admin/knowledge/documents/{doc['id']}/versions/{doc['versions'][0]['id']}/approve", {})
    assert r.status_code == 200, r.text
    return r.json()


def test_greeting_once_history_and_isolation(login, world):
    alice, bob = login("alice"), login("bob")
    c = _new(alice, world)
    assert len(c["messages"]) == 1 and c["messages"][0]["kind"] == "greeting" and c["starters"]
    assert alice.get("/v1/conversations").json() == []  # greeting-only conversations are not listed
    _say(alice, c["id"], "hello")
    again = alice.get(f"/v1/conversations/{c['id']}").json()
    assert [m["seq"] for m in again["messages"]] == [1, 2, 3] and [m["kind"] for m in again["messages"]].count("greeting") == 1
    assert alice.get("/v1/conversations?q=hello").json()[0]["id"] == c["id"]
    assert bob.get(f"/v1/conversations/{c['id']}").status_code == 404
    assert bob.post(f"/v1/conversations/{c['id']}/messages", {"message": "hi"}).status_code == 404
    assert bob.delete(f"/v1/conversations/{c['id']}").status_code == 404


def test_rename_archive_delete(login, world):
    alice = login("alice")
    cid = _new(alice, world)["id"]
    _say(alice, cid, "hello")
    assert alice.patch(f"/v1/conversations/{cid}", {"title": "My chat"}).json()["title"] == "My chat"
    assert alice.patch(f"/v1/conversations/{cid}", {"status": "archived"}).status_code == 200
    assert alice.post(f"/v1/conversations/{cid}/messages", {"message": "hi"}).status_code == 409
    assert alice.get("/v1/conversations?status=archived").json()[0]["id"] == cid
    assert alice.delete(f"/v1/conversations/{cid}").status_code == 204
    assert alice.get(f"/v1/conversations/{cid}").status_code == 404


def test_translate_still_works_inside_conversation(login, world):
    alice = login("alice")
    cid = _new(alice, world)["id"]
    r = _say(alice, cid, 'Translate "Good morning" from English to German')
    assert r["translation"] and r["actions"][0]["type"] == "open_in_workspace"
    assert alice.get(f"/v1/conversations/{cid}").json()["messages"][-1]["translation"]


def test_unapproved_knowledge_is_never_used_and_no_policy_is_invented(login, world, monkeypatch):
    calls = []
    monkeypatch.setattr(assistant_client, "chat", lambda m: calls.append(m) or ("Turnaround is 48 hours.", "stop"))
    alice, tina = login("alice"), login("tina")
    cid = _new(alice, world)["id"]
    doc = _kb(tina)  # draft
    r = _say(alice, cid, "What is the TNI turnaround policy for Swahili translations?")
    assert "48 hours" not in r["reply"] and not r["sources"] and "approved" in r["reply"].lower()
    assert not calls  # no model call without a source
    _approve(tina, doc)
    monkeypatch.setattr(assistant_client, "chat", lambda m: ("Swahili translations must be returned within five working days.", "stop"))
    r = _say(alice, cid, "What is the TNI turnaround policy for Swahili translations?")
    assert r["sources"] and r["sources"][0]["title"] == "Turnaround policy" and "five working days" in r["reply"]


def test_knowledge_deactivation_audience_and_access(login, world):
    alice, tina, rita = login("alice"), login("tina"), login("rita")
    assert alice.get("/v1/admin/knowledge/documents").status_code == 403
    assert alice.post("/v1/admin/knowledge/documents", {"title": "x", "category": "faq", "text": "y"}).status_code == 403
    doc = _approve(tina, _kb(tina, audience_roles=["reviewer"]))
    cid_a = _new(alice, world)["id"]
    assert not _say(alice, cid_a, "What is the TNI turnaround for Swahili translations?")["sources"]  # wrong audience
    cid_r = _new(rita, world)["id"]
    r = _say(rita, cid_r, "What is the TNI turnaround for Swahili translations?")
    assert r["sources"], r
    assert tina.post(f"/v1/admin/knowledge/documents/{doc['id']}/deactivate", {}).status_code == 200
    assert not _say(rita, cid_r, "What is the TNI turnaround for Swahili translations?")["sources"]


def test_new_version_replaces_old_and_platform_guide_is_protected(login, world):
    tina = login("tina")
    from app import knowledge
    from app.database import SessionLocal

    with SessionLocal() as db:
        knowledge.seed_platform_guide(db)
    guide = next(d for d in tina.get("/v1/admin/knowledge/documents").json() if d["system_managed"])
    assert guide["status"] == "approved" and guide["chunk_count"] > 0
    assert tina.post(f"/v1/admin/knowledge/documents/{guide['id']}/deactivate", {}).status_code == 409
    doc = _approve(tina, _kb(tina))
    r = tina.post(f"/v1/admin/knowledge/documents/{doc['id']}/versions", {"text": "# Turnaround\nNow seven working days."}).json()
    assert r["approved_version"] == 1 and len(r["versions"]) == 2
    new_id = r["versions"][0]["id"]
    r = tina.post(f"/v1/admin/knowledge/documents/{doc['id']}/versions/{new_id}/approve", {}).json()
    assert r["approved_version"] == 2


def test_assistant_down_gives_fallback_and_no_engine_words(login, world, monkeypatch):
    monkeypatch.setattr(assistant_client, "chat", lambda m: None)
    alice = login("alice")
    cid = _new(alice, world)["id"]
    r = _say(alice, cid, "Can you suggest a more natural way to say this sentence?")
    assert r["reply"].strip()
    monkeypatch.setattr(assistant_client, "chat", lambda m: ("I am powered by MADLAD, a Google model.", "stop"))
    r = _say(alice, cid, "Explain the difference between formal and informal tone")
    low = r["reply"].lower()
    assert "madlad" not in low and "google" not in low


def test_language_support_answer_is_deterministic(login, world):
    from app import languages
    from app.database import SessionLocal

    with SessionLocal() as db:
        languages.seed_language_catalog(db)
        languages.import_probe_evidence(db)
    alice = login("alice")
    cid = _new(alice, world)["id"]
    r = _say(alice, cid, "Do you support Yoruba?")
    assert "Yoruba" in r["reply"] and "not yet enabled" in r["reply"]
    langs = alice.get("/v1/language-support")
    assert langs.status_code == 200
    assert "madlad" not in json.dumps(langs.json()).lower()


def test_legacy_chat_creates_history(login, world):
    alice = login("alice")
    r = alice.post("/v1/chat", {"project_id": str(world.projects["p1"].id), "message": "hello"}).json()
    got = alice.get(f"/v1/conversations/{r['conversation_id']}").json()
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]


def test_platform_guide_is_never_used_as_tni_policy(login, world, monkeypatch):
    from app import knowledge
    from app.database import SessionLocal

    with SessionLocal() as db:
        knowledge.seed_platform_guide(db)
    monkeypatch.setattr(assistant_client, "chat", lambda m: ("TNI has no deadline policy.", "stop"))
    alice = login("alice")
    cid = _new(alice, world)["id"]
    r = _say(alice, cid, "What is the TNI policy on translation deadlines?")
    assert not r["sources"] and "approved" in r["reply"].lower()
