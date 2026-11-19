"""Per-language glossary (team-leader governed) and the doctrine reference HAN answers from."""
from __future__ import annotations

from app import knowledge
from app.database import SessionLocal
from app.han import assistant_client
from app.models.db import User
from app.security import auth as sec

from .conftest import PASSWORD


def _leader(world, languages=("sw",)):
    with SessionLocal() as db:
        u = User(email="lead@example.test", display_name="Lead Sw", role="team_leader", password_hash=sec.hash_password(PASSWORD))
        db.add(u)
        db.commit()
        uid = str(u.id)
    admin = None
    return uid, languages, admin


def _setup(login, world, languages=("sw",)):
    uid, langs, _ = _leader(world, languages)
    admin = login("tina")
    r = admin.put(f"/v1/glossary/leads/{uid}", {"languages": list(langs)})
    assert r.status_code == 200, r.text
    return admin, login("lead")


def _chat(sess, world, text):
    c = sess.post("/v1/conversations", {"project_id": str(world.projects["p1"].id)}).json()
    r = sess.post(f"/v1/conversations/{c['id']}/messages", {"message": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_only_the_language_team_leader_can_edit(login, world):
    admin, lead = _setup(login, world)
    ok = lead.post("/v1/glossary/sw/entries", {"source_text": "Righteousness", "target_text": "Haki"})
    assert ok.status_code == 201 and ok.json()["kind"] == "word"
    assert lead.post("/v1/glossary/de/entries", {"source_text": "Grace", "target_text": "Gnade"}).status_code == 403
    assert login("alice").post("/v1/glossary/sw/entries", {"source_text": "Grace", "target_text": "Neema"}).status_code == 403
    assert lead.post("/v1/glossary/sw/entries", {"source_text": " righteousness. ", "target_text": "X"}).status_code == 409
    assert admin.post("/v1/glossary/de/entries", {"source_text": "Grace", "target_text": "Gnade"}).status_code == 201
    assert login("alice").get("/v1/glossary/sw/entries").json()["total"] == 1  # everyone can read
    ov = login("alice").get("/v1/glossary/overview").json()
    assert ov["total_entries"] == 2 and not ov["can_manage_any"]


def test_import_export_and_edit(login, world):
    _, lead = _setup(login, world)
    csv_data = "english,translation,type,notes\nGrace,Neema,word,\nI am the Righteousness of God in Christ Jesus,Mimi ni haki ya Mungu katika Kristo Yesu,sentence,\n,missing,,\n"
    r = lead.client.post("/v1/glossary/sw/import", files={"file": ("g.csv", csv_data.encode(), "text/csv")}, headers={"X-CSRF-Token": lead.csrf})
    assert r.status_code == 200 and (r.json()["added"], r.json()["skipped"]) == (2, 1)
    items = lead.get("/v1/glossary/sw/entries?q=grace").json()["items"]
    assert len(items) == 1
    assert lead.patch(f"/v1/glossary/sw/entries/{items[0]['id']}", {"target_text": "Neema ya Mungu"}).json()["target_text"] == "Neema ya Mungu"
    assert "Neema ya Mungu" in lead.get("/v1/glossary/sw/export").text
    assert lead.delete(f"/v1/glossary/sw/entries/{items[0]['id']}").status_code == 204


def test_han_answers_from_the_glossary_and_does_not_guess(login, world, monkeypatch):
    monkeypatch.setattr(assistant_client, "chat", lambda m: ("Haki, I think.", "stop"))
    _, lead = _setup(login, world)
    lead.post("/v1/glossary/sw/entries", {"source_text": "Righteousness", "target_text": "Haki"})
    lead.post("/v1/glossary/sw/entries", {"source_text": "I am the Righteousness of God in Christ Jesus", "target_text": "Mimi ni haki ya Mungu katika Kristo Yesu", "kind": "sentence"})
    tr = login("alice")
    a = _chat(tr, world, "How is the word Righteousness translated in Swahili, based on the Approved TNI glossary?")
    assert "Haki" in a["reply"] and a.get("translation") is None and a["sources"][0]["category"] == "glossary"
    b = _chat(tr, world, 'Give me the translation of the expression "I am the Righteousness of God in Christ Jesus" in Swahili, according to the glossary')
    assert "Mimi ni haki ya Mungu katika Kristo Yesu" in b["reply"] and b.get("translation") is None
    c = _chat(tr, world, 'How is "Justification" translated in Swahili in the TNI glossary?')
    assert "no entry" in c["reply"] and "Haki" not in c["reply"]
    d = _chat(tr, world, 'Per the glossary, how is "Grace" translated in German?')
    assert "empty" in d["reply"]


def test_doctrine_reference_is_loaded_and_answers_definitions(login, world, monkeypatch):
    with SessionLocal() as db:
        assert "loaded" in knowledge.seed_doctrine_reference(db)
        assert "already" in knowledge.seed_doctrine_reference(db)
    seen = []
    monkeypatch.setattr(assistant_client, "chat", lambda m: seen.append(m[0]["content"]) or ("It is God's own rightness given as a gift.", "stop"))
    r = _chat(login("alice"), world, "Han, what is the definition of Righteousness according to Pastor Chris teaching?")
    assert r["sources"] and r["sources"][0]["category"] == "doctrine"
    assert "gift" in r["reply"] and "imparted" in seen[-1]
    monkeypatch.setattr(assistant_client, "chat", lambda m: None)
    j = _chat(login("alice"), world, "What is the definition of Justification?")
    assert "declared" in j["reply"].lower() or "legal" in j["reply"].lower()
    n = _chat(login("alice"), world, "What is the definition of Zorbulation according to Pastor Chris?")
    assert "reference" in n["reply"] and not n["sources"]
