"""HTTP-layer tests for the assistant service with an injected fake backend (no model is loaded)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assistant import create_app  # noqa: E402

H = {"Authorization": "Bearer tok"}


class Fake:
    def chat(self, messages, max_tokens, temperature):
        if "boom" in messages[-1]["content"]:
            raise RuntimeError("internal path /models/secret.gguf")
        return f"echo:{messages[-1]['content']}", "stop"

    def embed(self, texts, kind):
        return [[float(len(t)), 1.0] for t in texts]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("HAN_INFERENCE_TOKEN", "tok")
    return TestClient(create_app(Fake()))


def test_auth_required(client):
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert client.post("/chat", json=body).status_code == 401
    assert client.post("/chat", json=body, headers={"Authorization": "Bearer x"}).status_code == 401
    assert client.post("/chat", json=body, headers=H).json() == {"text": "echo:hi", "finish_reason": "stop"}


def test_embed_contract_and_validation(client):
    r = client.post("/embed", json={"texts": ["a", "bb"], "kind": "query"}, headers=H)
    assert r.json() == {"embeddings": [[1.0, 1.0], [2.0, 1.0]]}
    assert client.post("/embed", json={"texts": [], "kind": "query"}, headers=H).status_code == 422
    assert client.post("/embed", json={"texts": ["a"], "kind": "other"}, headers=H).status_code == 422
    assert client.post("/chat", json={"messages": [{"role": "root", "content": "x"}]}, headers=H).status_code == 422


def test_errors_do_not_leak(client):
    r = client.post("/chat", json={"messages": [{"role": "user", "content": "boom"}]}, headers=H)
    assert r.status_code == 500 and "secret" not in r.text and "/models" not in r.text


def test_unconfigured(monkeypatch):
    monkeypatch.delenv("HAN_INFERENCE_TOKEN", raising=False)
    assert TestClient(create_app(Fake())).post("/chat", json={"messages": [{"role": "user", "content": "x"}]}, headers=H).status_code == 503
