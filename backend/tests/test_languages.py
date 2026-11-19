"""Language registry, capability matrix and admin language tools."""
from __future__ import annotations

from app import languages
from app.database import SessionLocal
from app.models.db import LanguageDirection
from app.models.registry import ADAPTER_OVERRIDES
from app.models.internal_schemas import ProviderResult
from sqlalchemy import select

from tests.conftest import Session


def _seed():
    with SessionLocal() as db:
        languages.seed_language_catalog(db)
        languages.import_probe_evidence(db)
        return db.execute(select(LanguageDirection).where(LanguageDirection.source_code == "en", LanguageDirection.target_code == "yo")).scalar_one()


def test_catalog_import_does_not_enable_anything(world):
    row = _seed()
    assert row.readiness_tier == "unsupported" and row.technical_status in ("passed", "degraded")
    with SessionLocal() as db:
        assert len(languages.load_catalog()["languages"]) >= 419
        assert languages.enable_pilot_directions(db) > 50
        assert db.get(LanguageDirection, ("en", "yo")).readiness_tier == "experimental"
        assert {d.readiness_tier for d in db.execute(select(LanguageDirection)).scalars()} <= {"unsupported", "experimental", "assisted", "production"}
        assert db.get(LanguageDirection, ("en", "de")).readiness_tier == "assisted"  # pre-existing human decisions are untouched
        assert not any(d.readiness_tier == "production" and d.technical_status != "passed" for d in db.execute(select(LanguageDirection)).scalars())


def test_enable_all_opens_everything_except_failed_and_never_production(world):
    _seed()
    with SessionLocal() as db:
        assert languages.enable_all_directions(db) > 300
        rows = db.execute(select(LanguageDirection)).scalars().all()
        assert not any(d.readiness_tier == "unsupported" and d.technical_status != "failed" for d in rows)
        assert db.get(LanguageDirection, ("en", "de")).readiness_tier == "assisted"
        assert not any(d.readiness_tier == "production" for d in rows if d.technical_status != "passed")


def test_public_lists_hide_unsupported_and_engine_codes(world):
    _seed()
    alice = Session().login("alice@example.test")
    dirs = alice.get("/v1/language-directions").json()
    assert dirs and all(d["readiness_tier"] != "unsupported" for d in dirs)
    sup = alice.get("/v1/language-support").json()
    assert len(sup) >= 400 and {"availability", "native_name"} <= set(sup[0])
    assert "model_codes" not in alice.get("/v1/languages").text


def test_engine_codes_are_engine_protected(world):
    _seed()
    assert Session().login("tina@example.test").get("/v1/admin/models/language-codes").status_code == 403
    r = Session().login("gina@example.test").get("/v1/admin/models/language-codes")
    assert r.status_code == 200 and {"code": "sw", "model_codes": {"madlad": "sw"}} in r.json()


class _Fake:
    kind, family, external = "fake", "fake", False

    def configured(self): return True
    def supports(self, s, t): return True

    def translate(self, req):
        return ProviderResult(text=req.text if "echo" in req.text else "Habari za asubuhi", latency_ms=1, billed_chars=len(req.text))


def test_admin_direction_test_works_before_enabling(world):
    from app.models.db import Project
    _seed()
    with SessionLocal() as db:
        db.add(Project(name="Pilot", pilot_opt_in=True))
        db.commit()
    ADAPTER_OVERRIDES["dev-mock"] = _Fake()
    tina = Session().login("tina@example.test")
    r = tina.post("/v1/admin/language-directions/test", {"source_code": "en", "target_code": "yo", "text": "Good morning"})
    assert r.status_code == 200 and r.json()["technical_status"] == "passed"
    assert tina.post("/v1/admin/language-directions/test", {"source_code": "en", "target_code": "yo", "text": "echo"}).json()["technical_status"] == "degraded"
    with SessionLocal() as db:
        assert db.get(LanguageDirection, ("en", "yo")).readiness_tier == "unsupported"  # testing never enables
    assert Session().login("alice@example.test").post("/v1/admin/language-directions/test", {"source_code": "en", "target_code": "yo"}).status_code == 403


def test_validation_is_recorded_separately(world):
    _seed()
    tina = Session().login("tina@example.test")
    r = tina.put("/v1/admin/language-directions/validation", {"source_code": "en", "target_code": "yo", "validation_status": "in_review"})
    assert r.status_code == 200 and r.json()["validation_status"] == "in_review" and r.json()["readiness_tier"] == "unsupported"
