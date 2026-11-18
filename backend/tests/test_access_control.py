"""Access control: project membership, cross-project isolation, role gates, CSRF."""
from __future__ import annotations

from tests.conftest import translate


def test_unauthenticated_requests_are_rejected(anon):
    assert anon.get("/v1/projects").status_code == 401
    assert anon.get("/v1/auth/me").status_code == 401
    assert anon.post("/v1/auth/logout").status_code == 401


def test_login_failure_is_generic(anon, world):
    r = anon.client.post("/v1/auth/login", json={"email": "alice@example.test", "password": "wrong-password-123"})
    r2 = anon.client.post("/v1/auth/login", json={"email": "nobody@example.test", "password": "wrong-password-123"})
    assert r.status_code == r2.status_code == 401
    assert r.json() == r2.json()


def test_login_rate_limit(anon, world, monkeypatch):
    from app import ratelimit
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_auth_per_min", 3)
    codes = [anon.client.post("/v1/auth/login", json={"email": "alice@example.test", "password": "x" * 12}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3] == 429
    ratelimit.reset()


def test_translator_sees_only_own_projects(login, world):
    alice = login("alice")
    assert [p["name"] for p in alice.get("/v1/projects").json()] == ["Project One"]
    assert alice.get(f"/v1/projects/{world.projects['p1'].id}").status_code == 200
    assert alice.get(f"/v1/projects/{world.projects['p2'].id}").status_code == 404
    assert alice.get("/v1/projects/not-a-uuid").status_code == 404


def test_cross_project_access_is_denied_everywhere(login, world):
    alice, bob = login("alice"), login("bob")
    p1, p2 = world.projects["p1"], world.projects["p2"]
    created = translate(alice, p1)
    assert created.status_code == 201
    tid, vid = created.json()["translation_id"], created.json()["version_id"]

    assert bob.get(f"/v1/translations/{tid}").status_code == 404
    assert bob.post(f"/v1/translations/{tid}/versions", {"target_text": "x", "parent_version_id": vid}).status_code == 404
    assert bob.post(f"/v1/versions/{vid}/approve", {"decision": "approved"}).status_code == 404
    assert translate(bob, p1).status_code == 404
    q = {"project_id": str(p1.id), "source_language": "en", "target_language": "de", "q": "Hello"}
    assert bob.get("/v1/tm/search", params=q).status_code == 404
    assert bob.get("/v1/terminology/search", params={k: v for k, v in q.items() if k != "q"}).status_code == 404
    assert bob.post("/v1/qa/check", {"project_id": str(p1.id), "source_text": "a", "target_text": "b", "source_language": "en", "target_language": "de"}).status_code == 404
    assert bob.get("/v1/translations", params={"project_id": str(p1.id)}).status_code == 404
    assert bob.post("/v1/translation-jobs", {"project_id": str(p1.id), "source_language": "en", "target_language": "de", "text": "Hi"}).status_code == 404
    assert bob.post("/v1/chat", {"project_id": str(p1.id), "message": "hello"}).status_code == 404
    assert translate(bob, p2).status_code == 201


def test_translators_cannot_see_each_others_work_but_reviewers_can(login, world, db_session=None):
    from app.database import SessionLocal
    from app.models.db import ProjectMember

    with SessionLocal() as db:
        db.add(ProjectMember(project_id=world.projects["p1"].id, user_id=world.users["bob"].id, role="translator", can_approve=True))
        db.commit()
    alice, bob, rita = login("alice"), login("bob"), login("rita")
    tid = translate(alice, world.projects["p1"]).json()["translation_id"]
    assert bob.get(f"/v1/translations/{tid}").status_code == 404
    assert rita.get(f"/v1/translations/{tid}").status_code == 200
    assert alice.get(f"/v1/translations/{tid}").status_code == 200


def test_csrf_required_for_unsafe_methods(login, world):
    alice = login("alice")
    r = alice.post("/v1/translate", {"project_id": str(world.projects["p1"].id), "source_language": "en", "target_language": "de", "text": "Hi"}, csrf=False)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "csrf_failed"
    r = alice.client.post("/v1/translate", json={}, headers={"X-CSRF-Token": "bogus"})
    assert r.status_code == 403


def test_logout_revokes_session(login, world):
    alice = login("alice")
    assert alice.post("/v1/auth/logout").status_code == 200
    assert alice.get("/v1/projects").status_code == 401


def test_admin_endpoints_require_admin_roles(login, world):
    for name in ("alice", "rita", "pam", "audrey"):
        s = login(name)
        assert s.get("/v1/admin/users").status_code == 403, name
        assert s.get("/v1/admin/projects").status_code == 403, name
    for name in ("tina", "tim", "gina"):
        assert login(name).get("/v1/admin/users").status_code == 200


def test_engine_details_only_for_technical_admin_or_granted(login, world):
    for path in ("/v1/admin/models", "/v1/admin/routing-events", "/v1/admin/usage", "/v1/admin/health"):
        assert login("alice").get(path).status_code == 403
        assert login("tina").get(path).status_code == 403, "tni_admin without explicit grant"
        assert login("audrey").get(path).status_code == 403
        assert login("tim").get(path).status_code == 200
        assert login("gina").get(path).status_code == 200, "tni_admin with engine_details_granted"


def test_audit_visibility(login, world):
    translate(login("alice"), world.projects["p1"])
    assert login("audrey").get("/v1/admin/audit-events").status_code == 200
    assert login("alice").get("/v1/admin/audit-events").status_code == 403
    actions = {e["action"] for e in login("tina").get("/v1/admin/audit-events?limit=200").json()}
    assert {"auth.login", "translation.draft_created"} <= actions


def test_tni_admin_cannot_create_technical_admin(login, world):
    tina = login("tina")
    r = tina.post("/v1/admin/users", {"email": "x@example.test", "display_name": "X", "role": "technical_admin"})
    assert r.status_code == 403
    r = tina.post("/v1/admin/users", {"email": "x@example.test", "display_name": "X", "role": "translator"})
    assert r.status_code == 201 and r.json()["generated_password"]
    assert login("tim").post("/v1/admin/users", {"email": "y@example.test", "display_name": "Y", "role": "technical_admin", "password": "a-long-password-123"}).status_code == 201


def test_disabled_user_cannot_login_or_use_session(anon, login, world):
    alice = login("alice")
    tina = login("tina")
    uid = str(world.users["alice"].id)
    assert tina.patch(f"/v1/admin/users/{uid}", {"status": "disabled"}).status_code == 200
    assert alice.get("/v1/projects").status_code == 401
    assert anon.client.post("/v1/auth/login", json={"email": "alice@example.test", "password": "correct-horse-battery-staple"}).status_code == 401
