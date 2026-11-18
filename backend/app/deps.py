"""FastAPI dependencies: DB session, authenticated user (cookie + CSRF), request metadata."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from .database import get_db
from .errors import ApiError, unauthenticated
from .models.db import User, UserSession
from .security import auth as sec
from .security.permissions import HumanActor

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy:
        # Behind the web server's reverse proxy the LAST entry is the address the proxy itself observed; earlier
        # entries are client-supplied and spoofable, so they must never be used for rate limiting or audit.
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _session_user(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get(get_settings().cookie_name)
    if not token:
        return None
    claims = sec.decode_session_token(token)
    if not claims:
        return None
    sess = db.get(UserSession, claims["jti"])
    if sess is None or sess.revoked_at is not None or sess.expires_at <= datetime.now(timezone.utc):
        return None
    user = db.get(User, sess.user_id)
    if user is None or user.status != "active":
        return None
    request.state.session_jti = sess.jti
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _session_user(request, db)
    if user is None:
        raise unauthenticated()
    if request.method in UNSAFE and not sec.csrf_valid(request.state.session_jti, request.headers.get("x-csrf-token")):
        audit.record("access.csrf_failed", actor=user, outcome="denied", object_type="request", ip=client_ip(request))
        raise ApiError(403, "csrf_failed", "Your session could not be verified. Please refresh the page and try again.")
    request.state.user = user
    return user


def get_user_no_csrf(request: Request, db: Session = Depends(get_db)) -> User:
    user = _session_user(request, db)
    if user is None:
        raise unauthenticated()
    return user


def get_human_actor(request: Request, user: User = Depends(get_current_user)) -> HumanActor:
    """Only dependency that can mint a HumanActor (needed for approval)."""
    return HumanActor._issue(user, request.state.session_jti)
