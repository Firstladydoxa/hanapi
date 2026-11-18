"""HAN model-runtime service (separate from the application so GPU capacity can be added without redesign).

POST /translate  {family, text, target_lang, source_lang?}  ->  {"translation": "..."}

* `family` selects the model: "madlad" | "nllb" | "afrinllb". Each is loaded lazily from the Hugging Face id or local
  path in HAN_INFERENCE_MODEL_<FAMILY> (for example HAN_INFERENCE_MODEL_MADLAD). No weights are shipped in this repository.
* Bearer-token authentication is required (HAN_INFERENCE_TOKEN). It is meant to sit on a private network, never the internet.
* Licensing is NOT decided here: confirm each model's licence/terms (see the HAN model registry) before enabling it.

Tested at the HTTP layer with an injected fake translator (CI) and manually with real weights: google/madlad400-3b-mt on
CPU (PyTorch 2.14 CPU, transformers 5.20). Translation quality is NOT evaluated and must be benchmarked by TNI translators
on target hardware (see README).
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Dict, Optional, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

log = logging.getLogger("han.inference")
FAMILIES = ("madlad", "nllb", "afrinllb")


class Translator(Protocol):
    def translate(self, family: str, text: str, target_lang: str, source_lang: Optional[str]) -> str: ...


class TranslateIn(BaseModel):
    family: str
    text: str = Field(min_length=1, max_length=20_000)
    target_lang: str = Field(min_length=1, max_length=32)
    source_lang: Optional[str] = Field(default=None, max_length=32)


class HFTranslator:
    """Transformers-based runtime (PyTorch). CTranslate2 can be added behind the same interface for faster CPU inference."""

    def __init__(self) -> None:
        self._models: Dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._generate_lock = threading.Lock()  # one generation at a time: concurrent calls only fight over the same CPU cores

    def _load(self, family: str):
        with self._lock:
            if family in self._models:
                return self._models[family]
            model_id = os.environ.get(f"HAN_INFERENCE_MODEL_{family.upper()}")
            if not model_id:
                raise HTTPException(503, f"model for '{family}' is not configured")
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # heavy import, only when needed

            log.info("loading model for family %s", family)
            tok = AutoTokenizer.from_pretrained(model_id)
            model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
            model.eval()
            self._models[family] = (tok, model)
            return self._models[family]

    def translate(self, family: str, text: str, target_lang: str, source_lang: Optional[str]) -> str:
        import torch

        tok, model = self._load(family)
        beams = max(1, int(os.environ.get("HAN_INFERENCE_BEAMS", "2")))
        if family == "madlad":  # target language selected through the `<2xx>` prefix already added by HAN
            inputs = tok(text, return_tensors="pt", truncation=True, max_length=1024)
            extra = {}
        else:  # NLLB / AfriNLLB: FLORES-200 source and target codes
            if source_lang:
                tok.src_lang = source_lang
            inputs = tok(text, return_tensors="pt", truncation=True, max_length=1024)
            extra = {"forced_bos_token_id": tok.convert_tokens_to_ids(target_lang)}
        budget = min(1024, max(32, int(inputs["input_ids"].shape[1] * 2) + 16))  # output length scales with the input
        with self._generate_lock, torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=budget, num_beams=beams, **extra)
        return tok.batch_decode(out, skip_special_tokens=True)[0]


def create_app(translator: Optional[Translator] = None) -> FastAPI:
    runtime: Translator = translator or HFTranslator()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # HAN_INFERENCE_PRELOAD=madlad[,nllb] loads weights at startup so the first translator request is not slow
        # (the first load of a 3B model takes ~1-2 minutes on CPU).
        if isinstance(runtime, HFTranslator):
            for family in filter(None, (f.strip() for f in os.environ.get("HAN_INFERENCE_PRELOAD", "").split(","))):
                if family in FAMILIES:
                    await run_in_threadpool(runtime._load, family)
                    # one tiny generation faults all weight pages into memory (the first call is otherwise ~1 minute slower)
                    await run_in_threadpool(runtime.translate, family, "<2de> Hello." if family == "madlad" else "Hello.", "de" if family == "madlad" else "deu_Latn", "eng_Latn")
        yield

    app = FastAPI(title="HAN inference", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def authorise(authorization: Optional[str] = Header(default=None)) -> None:
        token = os.environ.get("HAN_INFERENCE_TOKEN", "")
        if not token:
            raise HTTPException(503, "service is not configured")
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(401, "unauthorised")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/translate", dependencies=[Depends(authorise)])
    def translate(body: TranslateIn):
        if body.family not in FAMILIES:
            raise HTTPException(422, "unknown model family")
        try:
            text = runtime.translate(body.family, body.text, body.target_lang, body.source_lang)
        except HTTPException:
            raise
        except Exception:
            log.exception("translation failed")  # never echo content or internals to the caller
            raise HTTPException(500, "translation failed")
        return {"translation": text}

    return app


app = create_app()
