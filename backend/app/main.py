"""HAN backend application factory."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .errors import install_error_handlers
from .logging_config import configure_logging
from .middleware import EngineConfidentialityMiddleware, RequestContextMiddleware

log = logging.getLogger("han")


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_for_startup()
    configure_logging()
    app = FastAPI(title="HAN API", version="1.0.0", docs_url=None if settings.is_production else "/docs",
                  redoc_url=None, openapi_url=None if settings.is_production else "/openapi.json")
    install_error_handlers(app)
    if settings.cors_origin_list:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token"])
    app.add_middleware(EngineConfidentialityMiddleware)
    app.add_middleware(RequestContextMiddleware)

    from .api import admin, approvals, auth, chat, conversations, glossary, jobs, knowledge, memory, projects, qa, reviews, rhapsody, terminology, translate, translations

    for module in (auth, projects, translate, translations, approvals, memory, terminology, qa, jobs, chat, conversations, knowledge, glossary, reviews, rhapsody, admin):
        app.include_router(module.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()
