"""Uniform, engine-agnostic error responses: {"detail": {"code", "message"}}."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("han.errors")

UNAVAILABLE_MESSAGE = "I'm sorry, I couldn't complete the translation at the moment. Please try again shortly."
UNSUPPORTED_MESSAGE = (
    "Automated translation isn't currently available for this language pair. "
    "Please contact TNI to arrange translation by a qualified human translator."
)
GENERIC_ERROR_MESSAGE = "Something went wrong on our side. Please try again shortly."


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: Optional[Dict[str, str]] = None):
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


def not_found(what: str = "resource") -> ApiError:
    return ApiError(404, "not_found", f"The requested {what} was not found.")


def forbidden(message: str = "You do not have permission to do that.") -> ApiError:
    return ApiError(403, "forbidden", message)


def unauthenticated() -> ApiError:
    return ApiError(401, "not_authenticated", "Please sign in to continue.")


def error_body(code: str, message: str) -> Dict[str, Any]:
    return {"detail": {"code": code, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            body = {"detail": exc.detail}
        else:
            code = {404: "not_found", 405: "method_not_allowed", 401: "not_authenticated", 403: "forbidden"}.get(
                exc.status_code, "error"
            )
            msg = {404: "The requested resource was not found."}.get(exc.status_code, "The request could not be completed.")
            body = error_body(code, msg)
        return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # Never echo submitted input back (it may be confidential text).
        fields = [
            {"field": ".".join(str(p) for p in e.get("loc", []) if p not in ("body", "query", "path")), "message": e.get("msg", "invalid")}
            for e in exc.errors()
        ]
        body = error_body("validation_error", "The request was not valid.")
        body["detail"]["fields"] = fields
        return JSONResponse(body, status_code=422)
