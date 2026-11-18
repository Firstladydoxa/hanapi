from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..deps import _session_user, client_ip, get_current_user
from ..errors import ApiError, unauthenticated
from ..models import schemas as S
from ..models.db import User, UserSession
from ..ratelimit import limit_auth
from ..security import auth as sec
from ..security import serializers as ser

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/login", response_model=S.SessionOut, dependencies=[Depends(limit_auth)])
def login(body: S.LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> S.SessionOut:
    ip = client_ip(request)
    user = db.execute(select(User).where(func.lower(User.email) == body.email.strip().lower())).scalar_one_or_none()
    ok = sec.verify_password(body.password, user.password_hash if user else None)
    if not ok or user is None or user.status != "active":
        audit.record("auth.login_failed", outcome="denied", object_type="user", ip=ip)
        raise ApiError(401, "invalid_credentials", "The email or password is incorrect.")
    if sec.needs_rehash(user.password_hash):
        user.password_hash = sec.hash_password(body.password)
    token, jti, exp = sec.create_session_token(user.id)
    db.add(UserSession(jti=jti, user_id=user.id, expires_at=exp, ip=ip))
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    s = get_settings()
    response.set_cookie(s.cookie_name, token, httponly=True, samesite="lax", secure=s.effective_cookie_secure,
                        max_age=s.session_ttl_minutes * 60, path="/")
    audit.record("auth.login", actor=user, object_type="user", object_id=user.id, ip=ip)
    return S.SessionOut(user=ser.user_out(user), csrf_token=sec.csrf_for(jti))


@router.post("/logout", response_model=S.OkOut)
def logout(request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> S.OkOut:
    sess = db.get(UserSession, request.state.session_jti)
    if sess is not None:
        sess.revoked_at = datetime.now(timezone.utc)
        db.commit()
    response.delete_cookie(get_settings().cookie_name, path="/")
    audit.record("auth.logout", actor=user, object_type="user", object_id=user.id, ip=client_ip(request))
    return S.OkOut()


@router.get("/me", response_model=S.SessionOut)
def me(request: Request, db: Session = Depends(get_db)) -> S.SessionOut:
    user = _session_user(request, db)
    if user is None:
        raise unauthenticated()
    return S.SessionOut(user=ser.user_out(user), csrf_token=sec.csrf_for(request.state.session_jti))
