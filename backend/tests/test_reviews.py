"""Reviewer scoring, evidence thresholds and administrator-only promotion."""
from __future__ import annotations

from app.database import SessionLocal
from app.models.db import LanguageDirection


def _score(sess, i, **kw):
    body = {"source_code": "en", "target_code": "de", "source_text": f"Sentence {i}", "draft_text": f"Satz {i}",
            "content_type": "general" if i % 2 else "scripture", "adequacy": 5, "fluency": 5, "severity": "none", **kw}
    return sess.post("/v1/reviews", body)


def _experimental():
    with SessionLocal() as db:
        d = db.get(LanguageDirection, ("en", "de"))
        d.readiness_tier, d.technical_status = "experimental", "passed"
        db.commit()


def test_thresholds_gate_promotion_and_only_admins_decide(login, world):
    _experimental()
    alice, rita, tina = login("alice"), login("rita"), login("tina")
    for i in range(15):
        assert _score(alice, i).status_code == 201
    assert _score(alice, 1).status_code == 409  # the same draft cannot be scored twice by one reviewer
    assert alice.get("/v1/admin/language-evidence").status_code == 403
    assert tina.post("/v1/admin/language-evidence/en/de/promote", {}).status_code == 409  # one reviewer is not enough
    for i in range(15, 30):
        assert _score(rita, i).status_code == 201
    ev = tina.get("/v1/admin/language-evidence/en/de").json()
    assert ev["summary"]["reviewers"] == 2 and ev["readiness"]["ready_for"] == "assisted"
    assert alice.post("/v1/admin/language-evidence/en/de/promote", {}).status_code == 403
    assert tina.post("/v1/admin/language-evidence/en/de/promote", {}).json()["tier"] == "assisted"
    with SessionLocal() as db:
        assert db.get(LanguageDirection, ("en", "de")).readiness_tier == "assisted"


def test_a_critical_error_blocks_readiness_and_unsupported_directions_are_refused(login, world):
    _experimental()
    alice, rita, tina = login("alice"), login("rita"), login("tina")
    for i in range(15):
        _score(alice, i)
        _score(rita, i + 100, severity="critical" if i == 0 else "none")
    ev = tina.get("/v1/admin/language-evidence/en/de").json()
    assert ev["summary"]["critical_errors"] == 1 and ev["readiness"]["ready_for"] is None
    assert not next(c for c in ev["readiness"]["criteria"] if c["key"] == "critical")["met"]
    r = alice.post("/v1/reviews", {"source_code": "en", "target_code": "zz", "source_text": "a", "draft_text": "b", "adequacy": 3, "fluency": 3, "severity": "none"})
    assert r.status_code == 422


def test_review_draft_generation_for_a_project_member(login, world):
    alice = login("alice")
    r = alice.post("/v1/reviews/draft", {"project_id": str(world.projects["p1"].id), "source_code": "en", "target_code": "de", "text": "Good morning"})
    assert r.status_code == 200 and r.json()["draft_text"]
    assert alice.get("/v1/reviews/samples").json()
