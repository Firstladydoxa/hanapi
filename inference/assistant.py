"""HAN assistant service: the conversational model and the embedding model (separate process from the translation engine).

POST /chat   {messages:[{role,content}], max_tokens, temperature}  ->  {"text": "...", "finish_reason": "stop|length"}
POST /embed  {texts:[...], kind: "query"|"passage"}                 ->  {"embeddings": [[...384 floats...], ...]}
GET  /healthz

* Chat: a small instruction-tuned GGUF model run with llama.cpp (HAN_ASSISTANT_CHAT_MODEL = path to the .gguf).
* Embeddings: multilingual-e5-small (HAN_ASSISTANT_EMBED_MODEL = local directory); 384-dimensional, cosine-normalised.
* Bearer-token authentication (HAN_INFERENCE_TOKEN, shared with the backend). Private network only.
* Model files are never committed. Licences are recorded in the HAN model registry (capability = chat / embedding).

Tested at the HTTP layer with injected fakes (CI) and manually with real weights on CPU. The chat model is small: it is good at
conversational help and rewriting, weak on specialised linguistics in low-resource languages. HAN never uses it to produce
translations (that is the translation engine's job) and grounds institutional answers in approved TNI documents.
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import List, Literal, Optional, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

log = logging.getLogger("han.assistant")


class Backend(Protocol):
    def chat(self, messages: List[dict], max_tokens: int, temperature: float) -> tuple[str, str]: ...
    def embed(self, texts: List[str], kind: str) -> List[List[float]]: ...


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=24_000)


class ChatIn(BaseModel):
    messages: List[Message] = Field(min_length=1, max_length=40)
    max_tokens: int = Field(default=300, ge=16, le=1024)
    temperature: float = Field(default=0.4, ge=0.0, le=1.2)


class EmbedIn(BaseModel):
    texts: List[str] = Field(min_length=1, max_length=64)
    kind: Literal["query", "passage"] = "passage"


class RealBackend:
    def __init__(self) -> None:
        self._llm = None
        self._emb = None
        self._lock = threading.Lock()
        self._gen_lock = threading.Lock()  # one generation at a time: concurrent calls only fight over the same cores

    def load_chat(self):
        with self._lock:
            if self._llm is None:
                from llama_cpp import Llama

                path = os.environ.get("HAN_ASSISTANT_CHAT_MODEL")
                if not path or not os.path.exists(path):
                    raise HTTPException(503, "chat model is not configured")
                self._llm = Llama(model_path=path, n_ctx=int(os.environ.get("HAN_ASSISTANT_CTX", "4096")),
                                  n_threads=int(os.environ.get("HAN_ASSISTANT_THREADS", "10")), verbose=False)
            return self._llm

    def load_embed(self):
        with self._lock:
            if self._emb is None:
                import torch
                from transformers import AutoModel, AutoTokenizer

                path = os.environ.get("HAN_ASSISTANT_EMBED_MODEL")
                if not path or not os.path.isdir(path):
                    raise HTTPException(503, "embedding model is not configured")
                torch.set_num_threads(int(os.environ.get("HAN_ASSISTANT_EMBED_THREADS", "4")))
                tok = AutoTokenizer.from_pretrained(path)
                model = AutoModel.from_pretrained(path).eval()
                self._emb = (tok, model)
            return self._emb

    def chat(self, messages, max_tokens, temperature):
        llm = self.load_chat()
        with self._gen_lock:
            out = llm.create_chat_completion(messages=messages, max_tokens=max_tokens, temperature=temperature, repeat_penalty=1.12, top_p=0.9)
        choice = out["choices"][0]
        return choice["message"]["content"], choice.get("finish_reason") or "stop"

    def embed(self, texts, kind):
        import torch

        tok, model = self.load_embed()
        prefixed = [f"{'query' if kind == 'query' else 'passage'}: {t}" for t in texts]
        batch = tok(prefixed, padding=True, truncation=True, max_length=512, return_tensors="pt")
        with torch.inference_mode():
            hidden = model(**batch).last_hidden_state
        mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
        pooled = (hidden * mask).sum(1) / mask.sum(1)
        pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return pooled.tolist()


def create_app(backend: Optional[Backend] = None) -> FastAPI:
    runtime: Backend = backend or RealBackend()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if isinstance(runtime, RealBackend) and os.environ.get("HAN_ASSISTANT_PRELOAD", "1") == "1":
            await run_in_threadpool(runtime.load_embed)
            await run_in_threadpool(runtime.load_chat)
            await run_in_threadpool(runtime.chat, [{"role": "user", "content": "Say hello."}], 8, 0.1)  # warm the weights
            await run_in_threadpool(runtime.embed, ["warm up"], "query")
        yield

    app = FastAPI(title="HAN assistant", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

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

    @app.post("/chat", dependencies=[Depends(authorise)])
    def chat(body: ChatIn):
        try:
            text, finish = runtime.chat([m.model_dump() for m in body.messages], body.max_tokens, body.temperature)
        except HTTPException:
            raise
        except Exception:
            log.exception("chat failed")  # never echo content or internals
            raise HTTPException(500, "chat failed")
        return {"text": text, "finish_reason": finish}

    @app.post("/embed", dependencies=[Depends(authorise)])
    def embed(body: EmbedIn):
        try:
            vectors = runtime.embed(body.texts, body.kind)
        except HTTPException:
            raise
        except Exception:
            log.exception("embed failed")
            raise HTTPException(500, "embedding failed")
        return {"embeddings": vectors}

    return app


app = create_app()
