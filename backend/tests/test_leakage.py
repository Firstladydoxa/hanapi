"""Engine confidentiality: translator-facing payloads, headers and errors never carry provider/model/routing data."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.database import SessionLocal
from app.models import registry as registry_mod
from app.models.db import LanguageDirection, ModelRegistry, RoutingEvent
from app.models.registry import DENYLIST_KEYS
from app.providers.base import ProviderAdapter, ProviderError
from tests.conftest import translate

APP = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN_KEYS = DENYLIST_KEYS | {"provider_id", "model_id", "route_reason", "latency_ms", "estimated_cost"}


def keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k).lower()
            yield from keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from keys(v)


def assert_clean(resp):
    """No forbidden structural keys, no registry identifiers anywhere outside user-content fields, no engine headers."""
    body = resp.json()
    assert not (set(keys(body)) & FORBIDDEN_KEYS), set(keys(body)) & FORBIDDEN_KEYS
    with SessionLocal() as db:
        ids = registry_mod.registry_identifiers(db)
    # scrub user-content fields before scanning raw text
    def scrub(o):
        if isinstance(o, dict):
            return {k: ("" if k in {"translated_text", "source_text", "target_text", "reply", "message", "text"} else scrub(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [scrub(v) for v in o]
        return o
    raw = json.dumps(scrub(body)).lower()
    for ident in ids | {"madlad", "nllb", "afrinllb", "google", "gpt"}:
        assert not re.search(rf"(?<![a-z0-9]){re.escape(ident)}(?![a-z0-9])", raw), f"{ident} leaked in {raw[:300]}"
    for h in resp.headers:
        assert h.lower() not in {"x-model", "x-provider", "x-route", "x-latency-ms", "server-timing"}


class Boom(ProviderAdapter):
    kind = "madlad"

    def map_language(self, code):
        return code

    def _translate(self, req):
        raise ProviderError("unavailable", "madlad-400-3b-mt exploded at https://internal.example")


def test_full_translator_flow_is_clean(login, world):
    alice = login("alice")
    r = translate(alice, world.projects["p1"], "The price is 5 euros.")
    assert r.status_code == 201, r.text
    assert_clean(r)
    tid, vid = r.json()["translation_id"], r.json()["version_id"]
    for resp in (
        alice.get(f"/v1/translations/{tid}"),
        alice.post(f"/v1/translations/{tid}/versions", {"target_text": "Der Preis beträgt 5 Euro.", "parent_version_id": vid}),
        alice.get("/v1/translations", params={"project_id": str(world.projects["p1"].id)}),
        alice.get(f"/v1/projects/{world.projects['p1'].id}"),
        alice.get("/v1/language-directions"),
        alice.post("/v1/chat", {"project_id": str(world.projects["p1"].id), "message": "Translate this text from English to German: Good morning"}),
        alice.post("/v1/chat", {"project_id": str(world.projects["p1"].id), "message": "Which engine did you use?"}),
        alice.post("/v1/translation-jobs", {"project_id": str(world.projects["p1"].id), "source_language": "en", "target_language": "de", "text": "One.\n\nTwo."}),
        alice.get("/v1/auth/me"),
    ):
        assert resp.status_code in (200, 201), resp.text
        assert_clean(resp)
    jobs = alice.get("/v1/translation-jobs", params={"project_id": str(world.projects["p1"].id)})
    assert_clean(jobs)
    assert_clean(alice.get(f"/v1/translation-jobs/{jobs.json()[0]['job_id']}"))


def test_error_paths_are_clean(login, world):
    alice = login("alice")
    p1 = world.projects["p1"]
    registry_mod.ADAPTER_OVERRIDES["dev-mock"] = Boom()
    r = translate(alice, p1)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "translation_unavailable"
    assert r.json()["detail"]["message"] == "I'm sorry, I couldn't complete the translation at the moment. Please try again shortly."
    assert_clean(r)
    assert "exploded" not in r.text and "internal.example" not in r.text
    unsupported = translate(alice, p1, source="en", target="sw")
    assert unsupported.status_code == 422 and unsupported.json()["detail"]["code"] == "direction_unsupported"
    assert_clean(unsupported)
    assert_clean(alice.get("/v1/translations/not-a-uuid"))
    assert_clean(alice.post("/v1/translate", {"project_id": "x"}))
    assert_clean(alice.get("/v1/nope"))


def test_admin_can_see_routing_but_translator_never(login, world):
    translate(login("alice"), world.projects["p1"])
    events = login("tim").get("/v1/admin/routing-events").json()
    assert events and events[0]["model_key"] == "dev-mock" and "route_reason" in events[0] and events[0]["latency_ms"] is not None
    assert events[0]["version_id"], "routing event is linked to the draft version"
    models = login("tim").get("/v1/admin/models").json()
    assert any(m["key"] == "madlad-400-3b-mt" for m in models)


def test_response_guard_blocks_a_leaking_route(login, world):
    """Even if a developer returns internal data by mistake, the safety-net middleware fails closed."""
    from app.main import app

    @app.get("/v1/_test_leak")
    def leak():
        return {"translated_text": "ok", "provider_id": "madlad-400-3b-mt"}

    @app.get("/v1/_test_leak_value")
    def leak_value():
        return {"note": "x", "status": "madlad-400-3b-mt"}

    @app.get("/v1/_test_user_text")
    def user_text():
        return {"translated_text": "Google and NLLB are named in the user's own text", "source_text": "madlad"}

    s = login("alice")
    r = s.get("/v1/_test_leak")
    assert r.status_code == 500 and "madlad" not in r.text and "provider_id" not in r.text
    assert s.get("/v1/_test_leak_value").status_code == 500
    assert s.get("/v1/_test_user_text").status_code == 200, "user content may legitimately contain any word"


def test_public_modules_do_not_import_internal_modules():
    forbidden = re.compile(r"^\s*(from|import)\s+[\w.]*(internal_schemas|gateway|router|registry)\b|^\s*from\s+\.+\s+import\s+.*\b(gateway|router|registry|internal_schemas)\b", re.M)
    for rel in ("models/schemas.py", "security/serializers.py"):
        src = (APP / rel).read_text()
        assert not forbidden.search(src), f"{rel} must not import internal routing modules"
    for path in APP.rglob("*.py"):
        text = path.read_text()
        assert "Sophia" not in text and "SOPHIA" not in text, f"stale product name in {path}"


def test_admin_non_engine_endpoints_are_clean(login, world):
    tina = login("tina")
    for path in ("/v1/admin/users", "/v1/admin/projects", "/v1/admin/language-directions", "/v1/admin/audit-events"):
        r = tina.get(path)
        assert r.status_code == 200
        assert_clean(r)
