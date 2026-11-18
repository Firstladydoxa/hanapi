"""HTTP-layer tests with an injected fake translator. No model is loaded and no weights are used."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import create_app  # noqa: E402


class Fake:
    def __init__(self):
        self.calls = []

    def translate(self, family, text, target_lang, source_lang):
        self.calls.append((family, text, target_lang, source_lang))
        if "boom" in text:
            raise RuntimeError("secret internal path /models/x")
        return f"[{family}->{target_lang}] {text}"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("HAN_INFERENCE_TOKEN", "s3cret-token")
    fake = Fake()
    c = TestClient(create_app(fake))
    c.fake = fake
    return c


H = {"Authorization": "Bearer s3cret-token"}


def test_requires_bearer_token(client):
    body = {"family": "nllb", "text": "Hello", "target_lang": "deu_Latn"}
    assert client.post("/translate", json=body).status_code == 401
    assert client.post("/translate", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/translate", json=body, headers=H).status_code == 200


def test_unconfigured_service_refuses(monkeypatch):
    monkeypatch.delenv("HAN_INFERENCE_TOKEN", raising=False)
    r = TestClient(create_app(Fake())).post("/translate", json={"family": "nllb", "text": "x", "target_lang": "de"}, headers=H)
    assert r.status_code == 503


def test_translate_contract(client):
    r = client.post("/translate", headers=H, json={"family": "madlad", "text": "<2de> Hello", "target_lang": "de"})
    assert r.json() == {"translation": "[madlad->de] <2de> Hello"}
    assert client.fake.calls == [("madlad", "<2de> Hello", "de", None)]


def test_validation(client):
    assert client.post("/translate", headers=H, json={"family": "gpt", "text": "x", "target_lang": "de"}).status_code == 422
    assert client.post("/translate", headers=H, json={"family": "nllb", "text": "", "target_lang": "de"}).status_code == 422
    assert client.post("/translate", headers=H, json={"family": "nllb", "text": "x" * 20_001, "target_lang": "de"}).status_code == 422


def test_failures_do_not_leak_internals(client):
    r = client.post("/translate", headers=H, json={"family": "nllb", "text": "boom", "target_lang": "de"})
    assert r.status_code == 500 and "secret" not in r.text and "/models" not in r.text


def test_health_is_open(client):
    assert client.get("/healthz").json() == {"status": "ok"}
