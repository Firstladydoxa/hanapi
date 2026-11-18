"""Model router eligibility, gateway fallback / timeouts / quotas. Uses fake adapters (no real providers are contacted)."""
from __future__ import annotations

import time

import pytest

from app.database import SessionLocal
from app.models import registry as registry_mod
from app.models.db import LanguageDirection, ModelDirectionScore, ModelRegistry, Project, RoutingEvent, UsageRecord
from app.models.gateway import ModelGateway, QuotaExceeded, TranslationUnavailable
from app.models.internal_schemas import ProviderRequest, ProviderResult
from app.models.router import DirectionUnsupported, plan_route
from app.providers.base import ProviderAdapter, ProviderError
from tests.conftest import translate


class Fake(ProviderAdapter):
    kind = "fake"

    def __init__(self, label, behaviour="ok", external=False, delay=0.0, langs=None):
        self.label, self.behaviour, self.external, self.delay, self.langs = label, behaviour, external, delay, langs
        self.calls = 0

    def map_language(self, code):
        if self.langs is not None and code not in self.langs:
            from app.providers.base import UnsupportedLanguage

            raise UnsupportedLanguage(code)
        return code

    def _translate(self, req):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.behaviour == "unavailable":
            raise ProviderError("unavailable", "down")
        if self.behaviour == "malformed":
            raise ProviderError("malformed", "garbage")
        if self.behaviour == "boom":
            raise RuntimeError("adapter bug")
        return f"{self.label}:{req.text}", {}


def add_model(key, adapter, *, enabled=True, cleared=True, deployed="deployed", external=False, priority=10, **kw):
    with SessionLocal() as db:
        db.add(ModelRegistry(key=key, provider="fake", model_name=f"fake/{key}", enabled=enabled, license_cleared=cleared,
                             license_evidence="test" if cleared else None, deployment_status=deployed, is_external=external,
                             priority=priority, **kw))
        db.commit()
    registry_mod.ADAPTER_OVERRIDES[key] = adapter
    registry_mod.invalidate_identifier_cache()


def disable_mock():
    with SessionLocal() as db:
        db.get(ModelRegistry, "dev-mock").enabled = False
        db.commit()


def project(world, name="p1"):
    with SessionLocal() as db:
        return db.get(Project, world.projects[name].id)


def plan(world, src="en", tgt="de", n=10, name="p1", **kw):
    with SessionLocal() as db:
        p = db.get(Project, world.projects[name].id)
        return plan_route(db, p, src, tgt, n, **kw)


def rejected(p):
    return {r.model_key: r.reason for r in p.rejections}


def test_default_registry_rows_are_never_routable(world):
    disable_mock()
    p = plan(world)
    assert p.candidates == []
    assert set(rejected(p).values()) <= {"provider_disabled"}


def test_unsupported_direction_and_experimental_pilot_gate(world):
    with pytest.raises(DirectionUnsupported):
        plan(world, "en", "sw")
    with pytest.raises(DirectionUnsupported):
        plan(world, "en", "fr")  # experimental, project has not opted in to pilots
    with pytest.raises(DirectionUnsupported):
        plan(world, "fr", "en")  # direction not defined at all
    with SessionLocal() as db:
        db.get(Project, world.projects["p1"].id).pilot_opt_in = True
        db.commit()
    assert plan(world, "en", "fr").tier == "experimental"


def test_license_gate_blocks_research_only_model(world):
    disable_mock()
    add_model("nllb-like", Fake("nllb"), cleared=False, license="CC-BY-NC-4.0")
    assert rejected(plan(world))["nllb-like"] == "license_not_cleared"
    with SessionLocal() as db:
        m = db.get(ModelRegistry, "nllb-like")
        m.license_cleared, m.license_evidence = True, "written legal clearance #1"
        db.commit()
    assert [c.model_key for c in plan(world).candidates] == ["nllb-like"]


def test_default_nllb_row_stays_uncleared_and_cannot_be_enabled_without_evidence(login, world):
    with SessionLocal() as db:
        m = db.get(ModelRegistry, "nllb-200-distilled-600m")
        assert m.license_cleared is False and "non-commercial" in (m.notes or "").lower() or "CC-BY-NC" in (m.license or "")
    tim = login("tim")
    r = tim.patch("/v1/admin/models/nllb-200-distilled-600m", {"license_cleared": True})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "license_evidence_required"
    r = tim.patch("/v1/admin/models/nllb-200-distilled-600m", {"license_cleared": True, "license_evidence": "Counsel letter 2026-11-01"})
    assert r.status_code == 200 and r.json()["license_cleared"] is True


def test_evaluation_routing_is_refused_in_production(world, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "env", "production")
    with pytest.raises(PermissionError):
        plan(world, evaluation=True)


def test_disabled_undeployed_unconfigured_and_language_gates(world):
    disable_mock()
    add_model("off", Fake("a"), enabled=False)
    add_model("undeployed", Fake("b"), deployed="not_deployed")
    add_model("narrow", Fake("c", langs={"en", "fr"}))
    add_model("big", Fake("d"), max_chars=5)
    r = rejected(plan(world, n=50))
    assert r["off"] == "provider_disabled" and r["undeployed"] == "not_deployed"
    assert r["narrow"] == "direction_not_covered" and r["big"] == "context_limit_exceeded"


def test_data_policy_blocks_external_providers(world):
    disable_mock()
    add_model("cloud", Fake("x", external=True), external=True)
    add_model("local", Fake("y"))
    assert rejected(plan(world))["cloud"] == "data_policy_blocks_external"
    assert [c.model_key for c in plan(world).candidates] == ["local"]
    with SessionLocal() as db:
        db.get(Project, world.projects["p1"].id).allow_external_processing = True
        db.commit()
    assert {c.model_key for c in plan(world).candidates} == {"cloud", "local"}


def test_benchmark_score_orders_candidates(world):
    disable_mock()
    add_model("weak", Fake("w"), priority=1)
    add_model("strong", Fake("s"), priority=99)
    with SessionLocal() as db:
        db.add_all([ModelDirectionScore(model_key="weak", source_code="en", target_code="de", benchmark_score=0.3),
                    ModelDirectionScore(model_key="strong", source_code="en", target_code="de", benchmark_score=0.9)])
        db.commit()
    assert [c.model_key for c in plan(world).candidates] == ["strong", "weak"]


def test_health_excludes_a_failing_provider(world):
    disable_mock()
    add_model("flaky", Fake("f"))
    with SessionLocal() as db:
        for _ in range(8):
            db.add(RoutingEvent(source_code="en", target_code="de", model_key="flaky", status="error", attempt_no=1))
        db.commit()
    assert rejected(plan(world))["flaky"] == "unhealthy_error_rate"


def gateway_translate(world, text="Hello"):
    with SessionLocal() as db:
        p = db.get(Project, world.projects["p1"].id)
        return ModelGateway(timeout_s=0.3, retries=1, backoff_s=0).translate(db, p, "en", "de", text, user_id=world.users["alice"].id)


def test_fallback_is_invisible_to_the_translator(login, world):
    disable_mock()
    bad, good = Fake("bad", "unavailable"), Fake("good")
    add_model("a-bad", bad, priority=1)
    add_model("b-good", good, priority=2)
    with SessionLocal() as db:
        db.add(ModelDirectionScore(model_key="a-bad", source_code="en", target_code="de", benchmark_score=0.99))
        db.commit()
    r = translate(login("alice"), world.projects["p1"], "Hello")
    assert r.status_code == 201 and r.json()["translated_text"] == "good:Hello"
    assert bad.calls == 2, "bounded retry then fallback"
    with SessionLocal() as db:
        events = db.query(RoutingEvent).order_by(RoutingEvent.attempt_no).all()
        assert [e.status for e in events] == ["error", "error", "success"] and events[-1].fallback is True
        assert db.query(UsageRecord).count() == 3


def test_timeout_then_fallback(world):
    disable_mock()
    slow = Fake("slow", delay=1.0)
    add_model("a-slow", slow, priority=1)
    add_model("b-fast", Fake("fast"), priority=2)
    with SessionLocal() as db:
        db.add(ModelDirectionScore(model_key="a-slow", source_code="en", target_code="de", benchmark_score=0.99))
        db.commit()
    res = gateway_translate(world)
    assert res.text == "fast:Hello" and res.fallback_used


def test_malformed_output_is_not_retried_but_falls_back(world):
    disable_mock()
    bad = Fake("m", "malformed")
    add_model("a-bad", bad, priority=1)
    add_model("b-ok", Fake("ok"), priority=2)
    with SessionLocal() as db:
        db.add(ModelDirectionScore(model_key="a-bad", source_code="en", target_code="de", benchmark_score=0.99))
        db.commit()
    assert gateway_translate(world).text == "ok:Hello" and bad.calls == 1


def test_unexpected_adapter_exception_is_contained(world):
    disable_mock()
    add_model("only", Fake("x", "boom"))
    with pytest.raises(TranslationUnavailable):
        gateway_translate(world)


def test_all_providers_fail_returns_generic_503(login, world):
    disable_mock()
    add_model("only", Fake("x", "unavailable"))
    r = translate(login("alice"), world.projects["p1"])
    assert r.status_code == 503 and r.json()["detail"]["code"] == "translation_unavailable"
    with SessionLocal() as db:
        assert db.query(RoutingEvent).filter_by(status="error").count() >= 1
        assert db.query(Project).count() == 2
    assert login("alice").get("/v1/translations", params={"project_id": str(world.projects["p1"].id)}).json() == [], "no orphan draft"


def test_no_route_when_nothing_configured_never_fabricates(login, world):
    disable_mock()
    r = translate(login("alice"), world.projects["p1"])
    assert r.status_code == 503
    with SessionLocal() as db:
        assert db.query(RoutingEvent).filter_by(status="no_route").count() == 1


def test_mock_provider_unavailable_in_production(world, monkeypatch):
    from app.config import get_settings
    from app.providers import build_adapter

    monkeypatch.setattr(get_settings(), "env", "production")
    assert build_adapter("mock") is None
    assert registry_mod.ensure_mock_model(SessionLocal()) is False


def test_character_quota_and_spend_limit(login, world):
    disable_mock()
    add_model("paid", Fake("p"), cost_per_1k_chars=10.0)
    with SessionLocal() as db:
        p = db.get(Project, world.projects["p1"].id)
        p.monthly_char_quota = 25
        db.commit()
    alice = login("alice")
    assert translate(alice, world.projects["p1"], "x" * 20).status_code == 201
    r = translate(alice, world.projects["p1"], "y" * 20)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "quota_exceeded"
    with SessionLocal() as db:
        p = db.get(Project, world.projects["p1"].id)
        p.monthly_char_quota, p.monthly_spend_limit = None, 0.001
        db.commit()
    assert translate(alice, world.projects["p1"], "z" * 50).status_code == 429


def test_spend_alert_threshold_is_audited(login, world):
    from app.models.db import AuditEvent

    disable_mock()
    add_model("paid", Fake("p"), cost_per_1k_chars=1.0)
    with SessionLocal() as db:
        p = db.get(Project, world.projects["p1"].id)
        p.monthly_spend_limit, p.spend_alert_pct = 0.1, 50
        db.commit()
    translate(login("alice"), world.projects["p1"], "a" * 100)  # cost 0.1 -> crosses 50%
    with SessionLocal() as db:
        assert db.query(AuditEvent).filter_by(action="quota.alert").count() == 1
