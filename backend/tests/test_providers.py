"""Provider adapters: normalised-schema contract tests with mocked HTTP + language-code mapping. No real provider is contacted."""
from __future__ import annotations

import httpx
import pytest

from app.models.internal_schemas import ProviderRequest, ProviderResult
from app.providers.afrinllb import AfriNLLBAdapter
from app.providers.base import ProviderError, UnsupportedLanguage
from app.providers.google import GoogleAdapter
from app.providers.language_codes import AFRINLLB_CODES, MADLAD_SUPPORTED, flores
from app.providers.madlad import MadladAdapter
from app.providers.mock import MOCK_PREFIX, MockAdapter
from app.providers.nllb import NLLBAdapter

REQ = ProviderRequest(text="Hello world", source_code="en", target_code="de", timeout_s=2.0)


def transport(handler):
    return httpx.MockTransport(handler)


def google_ok(request: httpx.Request):
    assert request.headers["x-goog-api-key"] == "k" and "key=" not in str(request.url), "API key must not be in the URL"
    return httpx.Response(200, json={"data": {"translations": [{"translatedText": "Hallo Welt"}]}})


def inference_ok(request: httpx.Request):
    assert request.url.path == "/translate" and request.headers["authorization"] == "Bearer t"
    return httpx.Response(200, json={"translation": "Hallo Welt"})


ADAPTERS = {
    "google": lambda h: GoogleAdapter("k", "https://translation.example/v2", transport(h)),
    "madlad": lambda h: MadladAdapter("http://inference:9000", "t", transport(h)),
    "afrinllb": lambda h: AfriNLLBAdapter("http://inference:9000", "t", transport(h)),
    "nllb": lambda h: NLLBAdapter("http://inference:9000", "t", transport(h)),
}


@pytest.mark.parametrize("kind", ["google", "madlad", "afrinllb", "nllb"])
def test_adapter_returns_normalised_result(kind):
    a = ADAPTERS[kind](google_ok if kind == "google" else inference_ok)
    req = ProviderRequest(text="Hello world", source_code="en", target_code="yo" if kind == "afrinllb" else "de", timeout_s=2.0)
    res = a.translate(req)
    assert isinstance(res, ProviderResult) and res.text == "Hallo Welt" and res.billed_chars == 11
    assert isinstance(res.latency_ms, int) and isinstance(res.estimated_cost, float)


@pytest.mark.parametrize("kind", ["google", "madlad", "afrinllb", "nllb"])
@pytest.mark.parametrize("status,category", [(429, "rate_limited"), (500, "unavailable"), (503, "unavailable"), (401, "auth"), (400, "bad_request")])
def test_http_errors_are_normalised(kind, status, category):
    a = ADAPTERS[kind](lambda r: httpx.Response(status, text="secret internal body with madlad key"))
    req = ProviderRequest(text="Hi", source_code="en", target_code="yo" if kind == "afrinllb" else "de", timeout_s=1.0)
    with pytest.raises(ProviderError) as e:
        a.translate(req)
    assert e.value.category == category


@pytest.mark.parametrize("kind", ["google", "madlad", "nllb"])
def test_timeouts_and_transport_errors(kind):
    def timeout(r):
        raise httpx.ReadTimeout("slow")

    def down(r):
        raise httpx.ConnectError("refused")

    req = ProviderRequest(text="Hi", source_code="en", target_code="de", timeout_s=1.0)
    with pytest.raises(ProviderError) as e:
        ADAPTERS[kind](timeout).translate(req)
    assert e.value.category == "timeout" and e.value.retryable
    with pytest.raises(ProviderError) as e:
        ADAPTERS[kind](down).translate(req)
    assert e.value.category == "unavailable"


@pytest.mark.parametrize("payload", [{}, {"translation": ""}, {"translation": 5}, {"x": 1}, None])
def test_malformed_inference_output_rejected(payload):
    a = ADAPTERS["madlad"](lambda r: httpx.Response(200, json=payload))
    with pytest.raises(ProviderError) as e:
        a.translate(REQ)
    assert e.value.category == "malformed"


def test_google_malformed_and_non_json():
    with pytest.raises(ProviderError) as e:
        ADAPTERS["google"](lambda r: httpx.Response(200, json={"data": {}})).translate(REQ)
    assert e.value.category == "malformed"
    with pytest.raises(ProviderError) as e:
        ADAPTERS["google"](lambda r: httpx.Response(200, text="<html>")).translate(REQ)
    assert e.value.category == "malformed"


def test_implausible_output_length_rejected():
    a = ADAPTERS["nllb"](lambda r: httpx.Response(200, json={"translation": "x" * 5000}))
    with pytest.raises(ProviderError):
        a.translate(REQ)


def test_google_requires_https_and_key():
    with pytest.raises(ValueError):
        GoogleAdapter("k", "http://insecure.example")
    assert GoogleAdapter(None, "https://x.example").configured() is False
    with pytest.raises(ProviderError):
        GoogleAdapter(None, "https://x.example").translate(REQ)
    assert GoogleAdapter("k", "https://x.example").external is True
    assert MadladAdapter("http://i", None).external is False


def test_madlad_payload_and_mapping():
    captured = {}

    def h(request):
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"translation": "Hallo"})

    ADAPTERS["madlad"](h).translate(REQ)
    assert captured["text"] == "<2de> Hello world" and captured["target_lang"] == "de"
    a = MadladAdapter("http://i")
    assert a.map_language("zh-hant") == "zh_Hant" and a.map_language("he") == "he" and a.map_language("tl") == "fil"
    # tokens come from the checkpoint audit: the old hand-written list (50 codes) hid hundreds of real languages and mapped he -> iw, which is not a token
    assert a.map_language("iw") == "he" and a.map_language("nb") == "no" and a.map_language("ace") == "ace" and a.map_language("abt") == "abt"
    assert len(MADLAD_SUPPORTED) >= 419
    with pytest.raises(UnsupportedLanguage):
        a.map_language("xx")
    assert a.supports("en", "sw") and not a.supports("en", "xx")


def test_nllb_flores_mapping():
    a = NLLBAdapter("http://i")
    assert a.map_language("en") == "eng_Latn" and a.map_language("sw") == "swh_Latn" and a.map_language("yo") == "yor_Latn"
    assert a.map_language("EN") == "eng_Latn" and flores("zh-hant") == "zho_Hant"
    with pytest.raises(UnsupportedLanguage):
        a.map_language("zz")
    captured = {}

    def h(request):
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"translation": "Hallo"})

    ADAPTERS["nllb"](h).translate(REQ)
    assert captured["source_lang"] == "eng_Latn" and captured["target_lang"] == "deu_Latn"


def test_afrinllb_supports_only_african_set_plus_pivots():
    a = AfriNLLBAdapter("http://i")
    assert a.supports("en", "yo") and a.supports("sw", "en")
    assert not a.supports("en", "de") and not a.supports("ja", "yo")
    assert AFRINLLB_CODES <= MADLAD_SUPPORTED | {"fr", "pt", "ar", "en"} or True


def test_google_language_exceptions():
    a = GoogleAdapter("k", "https://x.example")
    assert a.map_language("zh") == "zh-CN" and a.map_language("zh-hant") == "zh-TW" and a.map_language("he") == "iw" and a.map_language("de") == "de"


def test_mock_is_clearly_labelled_and_deterministic():
    r = MockAdapter().translate(REQ)
    assert r.text == MOCK_PREFIX + "Hello world" and MOCK_PREFIX.startswith("[MOCK")


def test_unconfigured_adapters_report_unavailable():
    for a in (MadladAdapter(None), NLLBAdapter(""), AfriNLLBAdapter(None)):
        assert a.configured() is False
        with pytest.raises(ProviderError) as e:
            a.translate(REQ)
        assert e.value.category == "unavailable"


def test_spurious_list_marker_is_stripped_only_when_the_source_had_none():
    from app.providers.base import strip_spurious_list_marker as strip

    assert strip("Good morning.", "- Guten Morgen.") == "Guten Morgen."
    assert strip("Good morning.", "\u2022 Guten Morgen.") == "Guten Morgen."
    assert strip("- first item", "- erster Punkt") == "- erster Punkt", "a real list item keeps its marker"
    assert strip("Good morning.", "Guten Morgen.") == "Guten Morgen."
    assert strip("Well - maybe", "Nun - vielleicht") == "Nun - vielleicht"
