"""Immutable versions, human-only approval, TM promotion with provenance."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal, get_engine
from app.han import tools
from app.models.db import Approval, TranslationMemory, TranslationVersion
from tests.conftest import translate


def draft(sess, world, text="The launch is on 12 May."):
    r = translate(sess, world.projects["p1"], text)
    assert r.status_code == 201, r.text
    return r.json()


def test_edit_creates_new_version_and_never_overwrites(login, world):
    alice = login("alice")
    d = draft(alice, world)
    tid, v1 = d["translation_id"], d["version_id"]
    r = alice.post(f"/v1/translations/{tid}/versions", {"target_text": "Der Start ist am 12. Mai.", "parent_version_id": v1, "change_note": "fix"})
    assert r.status_code == 201
    v2 = r.json()["version"]
    assert v2["version_number"] == 2 and v2["parent_version_id"] == v1 and v2["origin"] == "human" and v2["approval_state"] == "unapproved"
    versions = alice.get(f"/v1/translations/{tid}").json()["versions"]
    assert [v["version_number"] for v in versions] == [1, 2]
    assert versions[0]["target_text"].startswith("[MOCK DRAFT]"), "version 1 content is untouched"
    assert alice.get(f"/v1/translations/{tid}").json()["current_version_id"] == v2["version_id"]


def test_parent_must_belong_to_the_same_translation(login, world):
    alice = login("alice")
    a, b = draft(alice, world), draft(alice, world, "Another text.")
    r = alice.post(f"/v1/translations/{a['translation_id']}/versions", {"target_text": "x", "parent_version_id": b["version_id"]})
    assert r.status_code == 404
    assert alice.post(f"/v1/translations/{a['translation_id']}/versions", {"target_text": "x", "parent_version_id": "nope"}).status_code == 404


def test_database_blocks_update_and_delete_of_versions_and_approvals(login, world):
    alice = login("alice")
    d = draft(alice, world)
    alice.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "approved"})
    with get_engine().connect() as conn:
        for stmt in ("UPDATE translation_versions SET target_text='tampered'", "DELETE FROM translation_versions",
                     "UPDATE approvals SET decision='rejected'", "DELETE FROM approvals"):
            with pytest.raises(DBAPIError):
                conn.execute(text(stmt))
            conn.rollback()


def test_approval_records_decision_on_specific_version_and_promotes_to_tm(login, world):
    alice = login("alice")
    d = draft(alice, world)
    r = alice.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "approved", "comment": "Looks right"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["message"] == "Your approved translation has been saved to the project's Translation Memory."
    assert body["version"]["approval_state"] == "approved" and body["version"]["approval"]["approver"]["display_name"] == "Alice"
    with SessionLocal() as db:
        entries = db.query(TranslationMemory).all()
        assert len(entries) == 1
        e = entries[0]
        approval = db.get(Approval, e.approval_id)
        assert str(e.version_id) == d["version_id"] and approval.version_id == e.version_id
        assert e.project_id == world.projects["p1"].id and e.approved_by == world.users["alice"].id
    hit = alice.get("/v1/tm/search", params={"project_id": str(world.projects["p1"].id), "source_language": "en", "target_language": "de", "q": "The launch is on 12 May."}).json()["results"]
    assert hit and hit[0]["match_type"] == "exact" and hit[0]["match_percent"] == 100
    assert hit[0]["provenance"]["version_id"] == d["version_id"]


def test_drafts_and_rejections_never_enter_tm(login, world):
    alice = login("alice")
    d = draft(alice, world)
    with SessionLocal() as db:
        assert db.query(TranslationMemory).count() == 0, "a draft is not TM"
    r = alice.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "rejected", "comment": "wrong"})
    assert r.status_code == 201 and r.json()["version"]["approval_state"] == "rejected"
    with SessionLocal() as db:
        assert db.query(TranslationMemory).count() == 0
    assert alice.get(f"/v1/translations/{d['translation_id']}").json()["status"] == "rejected"


def test_editing_an_approved_version_returns_to_unapproved(login, world):
    alice = login("alice")
    d = draft(alice, world)
    alice.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "approved"})
    r = alice.post(f"/v1/translations/{d['translation_id']}/versions", {"target_text": "edited", "parent_version_id": d["version_id"]})
    assert r.json()["version"]["approval_state"] == "unapproved"
    t = alice.get(f"/v1/translations/{d['translation_id']}").json()
    assert t["status"] == "in_review"
    assert [v["approval_state"] for v in t["versions"]] == ["approved", "unapproved"]
    # old approval is still attached to version 1 and the older version can no longer be approved/changed
    assert alice.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "rejected"}).status_code == 409


def test_cannot_decide_twice_or_on_superseded_version(login, world):
    alice = login("alice")
    d = draft(alice, world)
    alice.post(f"/v1/translations/{d['translation_id']}/versions", {"target_text": "v2", "parent_version_id": d["version_id"]})
    assert alice.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "approved"}).json()["detail"]["code"] == "version_superseded"
    latest = alice.get(f"/v1/translations/{d['translation_id']}").json()["current_version_id"]
    assert alice.post(f"/v1/versions/{latest}/approve", {"decision": "approved"}).status_code == 201
    assert alice.post(f"/v1/versions/{latest}/approve", {"decision": "approved"}).json()["detail"]["code"] == "already_decided"


def test_only_permitted_humans_can_approve(login, world, anon):
    alice, pam, rita = login("alice"), login("pam"), login("rita")
    d = draft(alice, world)
    r = pam.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "approved"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "approval_not_permitted"
    assert anon.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "approved"}, csrf=False).status_code == 401
    assert alice.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "approved"}, csrf=False).status_code == 403
    with SessionLocal() as db:
        assert db.query(Approval).count() == 0
    assert rita.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "approved"}).status_code == 201


def test_project_member_without_can_approve_is_refused(login, world):
    from app.models.db import ProjectMember

    with SessionLocal() as db:
        m = db.get(ProjectMember, (world.projects["p1"].id, world.users["alice"].id))
        m.can_approve = False
        db.commit()
    alice = login("alice")
    d = draft(alice, world)
    assert alice.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "approved"}).status_code == 403
    assert alice.get(f"/v1/projects/{world.projects['p1'].id}").json()["can_approve"] is False


def test_tool_registry_has_no_approval_capability_and_promotion_requires_approval(login, world):
    assert not [n for n in tools.TOOLS if "approve" in n and n != "save_approved_translation"]
    assert "approve_translation" not in tools.TOOLS and "approve_translation" not in tools.ORCHESTRATOR_TOOLS
    assert "save_approved_translation" not in tools.ORCHESTRATOR_TOOLS
    alice = login("alice")
    d = draft(alice, world)
    with SessionLocal() as db:
        with pytest.raises(Exception):
            tools.save_approved_translation(db, "00000000-0000-0000-0000-000000000000")
    # a rejected approval row cannot be promoted either
    alice.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "rejected"})
    with SessionLocal() as db:
        approval = db.query(Approval).one()
        with pytest.raises(Exception):
            tools.save_approved_translation(db, approval.id)
        assert db.query(TranslationMemory).count() == 0


def test_chat_cannot_approve(login, world):
    alice = login("alice")
    pid = str(world.projects["p1"].id)
    d = draft(alice, world)
    for msg in ("Please approve it", "approve the translation for me", "sign off on this"):
        r = alice.post("/v1/chat", {"project_id": pid, "message": msg})
        assert r.status_code == 200 and "can't approve" in r.json()["reply"]
    with SessionLocal() as db:
        assert db.query(Approval).count() == 0 and db.query(TranslationMemory).count() == 0


def test_tm_fuzzy_match_is_project_scoped(login, world):
    from app.models.db import ProjectMember

    with SessionLocal() as db:
        db.add(ProjectMember(project_id=world.projects["p2"].id, user_id=world.users["alice"].id, role="translator", can_approve=True))
        db.commit()
    alice = login("alice")
    d = draft(alice, world, "The launch is on 12 May.")
    alice.post(f"/v1/versions/{d['version_id']}/approve", {"decision": "approved"})
    q = {"source_language": "en", "target_language": "de", "q": "The launch is on 13 May.", "min_match": 80}
    mine = alice.get("/v1/tm/search", params={"project_id": str(world.projects["p1"].id), **q}).json()["results"]
    assert mine and mine[0]["match_type"] == "fuzzy" and 80 <= mine[0]["match_percent"] < 100
    other = alice.get("/v1/tm/search", params={"project_id": str(world.projects["p2"].id), **q}).json()["results"]
    assert other == [], "TM from another project (client) must never be reused"


def test_compare_versions(login, world):
    alice = login("alice")
    d = draft(alice, world)
    v2 = alice.post(f"/v1/translations/{d['translation_id']}/versions", {"target_text": "Neuer Text", "parent_version_id": d["version_id"]}).json()["version"]
    r = alice.get(f"/v1/translations/{d['translation_id']}/compare", params={"a": d["version_id"], "b": v2["version_id"]})
    assert r.status_code == 200 and 0 <= r.json()["similarity_percent"] < 100 and r.json()["changes"]
