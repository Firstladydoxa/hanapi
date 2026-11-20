from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import audit
from .. import email as mail
from ..config import get_settings
from ..database import get_db
from ..deps import _session_user, client_ip, get_current_user
from ..errors import ApiError, unauthenticated
from ..models import schemas as S
from ..models.db import EmailAuthChallenge, RegistrationReminder, User, UserSession
from ..ratelimit import limit_auth
from ..security import auth as sec
from ..security import serializers as ser
import jwt

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/login", response_model=S.SessionOut, dependencies=[Depends(limit_auth)])
def login(body: S.LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> S.SessionOut:
    ip = client_ip(request)
    user = db.execute(select(User).where(func.lower(User.email) == body.email.strip().lower())).scalar_one_or_none()
    ok = sec.verify_password(body.password, user.password_hash if user else None)
    if not ok or user is None or user.status != "active":
        audit.record("auth.login_failed", outcome="denied", object_type="user", ip=ip)
        raise ApiError(401, "invalid_credentials", "The email or password is incorrect.")
    if not user.email_verified:
        # Resend only when no live code was issued in the cooldown window, so repeated sign-in attempts cannot flood the inbox.
        try:
            _send_code(db, user, "verify_email")
        except ApiError:
            db.rollback()
        audit.record("auth.login_unverified_email", outcome="denied", object_type="user", object_id=user.id, ip=ip)
        raise ApiError(403, "email_not_verified", "Your registration is not complete. We have sent a verification code to your email.")
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


def _email_code_hash(user_id, purpose: str, code: str) -> str:
    settings = get_settings()
    pepper = settings.email_auth_pepper or settings.secret_key
    value = f"{user_id}:{purpose}:{code}".encode()
    return hmac.new(pepper.encode(), value, hashlib.sha256).hexdigest()


def _issue_code(db: Session, user: User, purpose: str, force: bool = False) -> str:
    # Serialize code issuance per account to prevent concurrent resends leaving two live codes.
    db.execute(select(User).where(User.id == user.id).with_for_update()).scalar_one()
    now = datetime.now(timezone.utc)
    cooldown = timedelta(seconds=get_settings().email_code_resend_cooldown_seconds)
    recent = db.execute(select(EmailAuthChallenge).where(
        EmailAuthChallenge.user_id == user.id, EmailAuthChallenge.purpose == purpose,
        EmailAuthChallenge.created_at >= now - cooldown, EmailAuthChallenge.consumed_at.is_(None),
        EmailAuthChallenge.invalidated_at.is_(None)
    ).order_by(EmailAuthChallenge.created_at.desc())).scalars().first()
    if recent and not force:
        raise ApiError(429, "code_resend_cooldown", "Please wait before requesting another code.")
    db.execute(update(EmailAuthChallenge).where(
        EmailAuthChallenge.user_id == user.id, EmailAuthChallenge.purpose == purpose,
        EmailAuthChallenge.consumed_at.is_(None), EmailAuthChallenge.invalidated_at.is_(None)
    ).values(invalidated_at=now))
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(EmailAuthChallenge(user_id=user.id, purpose=purpose, code_hash=_email_code_hash(user.id, purpose, code),
        expires_at=now + timedelta(minutes=get_settings().email_code_ttl_minutes)))
    db.flush()
    return code


def _consume_code(db: Session, user: User, purpose: str, code: str) -> bool:
    now = datetime.now(timezone.utc)
    challenge = db.execute(select(EmailAuthChallenge).where(
        EmailAuthChallenge.user_id == user.id, EmailAuthChallenge.purpose == purpose,
        EmailAuthChallenge.consumed_at.is_(None), EmailAuthChallenge.invalidated_at.is_(None),
        EmailAuthChallenge.expires_at > now
    ).order_by(EmailAuthChallenge.created_at.desc()).with_for_update()).scalars().first()
    if challenge is None or challenge.attempts >= get_settings().email_code_max_attempts:
        return False
    challenge.attempts += 1
    if not hmac.compare_digest(challenge.code_hash, _email_code_hash(user.id, purpose, code)):
        if challenge.attempts >= get_settings().email_code_max_attempts:
            challenge.invalidated_at = now
        db.flush()
        return False
    challenge.consumed_at = now
    db.execute(update(EmailAuthChallenge).where(
        EmailAuthChallenge.user_id == user.id, EmailAuthChallenge.purpose == purpose,
        EmailAuthChallenge.id != challenge.id, EmailAuthChallenge.consumed_at.is_(None),
        EmailAuthChallenge.invalidated_at.is_(None)
    ).values(invalidated_at=now))
    return True


def _send_code(db: Session, user: User, purpose: str, force: bool = False) -> None:
    code = _issue_code(db, user, purpose, force=force)
    db.commit()
    if not mail.send_code(user.email, user.display_name, code, purpose, get_settings().email_code_ttl_minutes):
        raise ApiError(503, "email_delivery_unavailable", "We could not send your email right now. Please try again shortly.")


@router.post("/register", status_code=202, dependencies=[Depends(limit_auth)])
def register(body: S.RegisterRequest, request: Request, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    existing = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
    if existing is not None and (existing.email_verified or existing.status != "active"):
        raise ApiError(409, "registration_unavailable", "We could not start registration for this address. Try signing in or resetting your password.")
    if existing is not None:
        # Unverified account: restart registration with the newly supplied details and a fresh code.
        existing.display_name = body.display_name.strip()
        existing.password_hash = sec.hash_password(body.password)
        db.add(RegistrationReminder(user_id=existing.id,
            due_at=datetime.now(timezone.utc) + timedelta(minutes=get_settings().registration_reminder_delay_minutes)))
        db.commit()
        _send_code(db, existing, "verify_email", force=True)
        return {"ok": True, "email": existing.email, "message": "Enter the six-digit code sent to your email."}
    user = User(email=email, display_name=body.display_name.strip(), role="translator",
        password_hash=sec.hash_password(body.password), status="active", email_verified=False)
    db.add(user)
    try:
        db.flush()
        code = _issue_code(db, user, "verify_email")
        reminder = RegistrationReminder(user_id=user.id,
            due_at=datetime.now(timezone.utc) + timedelta(minutes=get_settings().registration_reminder_delay_minutes))
        db.add(reminder)
        db.commit()
    except Exception:
        db.rollback()
        raise
    if not mail.send_code(user.email, user.display_name, code, "verify_email", get_settings().email_code_ttl_minutes):
        raise ApiError(503, "email_delivery_unavailable", "Your registration was saved, but we could not send the verification email. Use resend verification to try again.")
    audit.record("auth.registration_started", object_type="user", object_id=user.id, ip=client_ip(request))
    return {"ok": True, "email": user.email, "message": "Enter the six-digit code sent to your email."}


@router.post("/verify-email", dependencies=[Depends(limit_auth)])
def verify_email(body: S.EmailCodeRequest, request: Request, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(func.lower(User.email) == body.email.strip().lower())).scalar_one_or_none()
    if user is None or user.email_verified:
        raise ApiError(400, "invalid_or_expired_code", "This verification code is invalid or expired. Request a new code.")
    if not _consume_code(db, user, "verify_email", body.code):
        db.commit()
        raise ApiError(400, "invalid_or_expired_code", "This verification code is invalid or expired. Request a new code.")
    user.email_verified = True
    db.execute(update(RegistrationReminder).where(RegistrationReminder.user_id == user.id,
        RegistrationReminder.cancelled_at.is_(None)).values(cancelled_at=datetime.now(timezone.utc)))
    db.commit()
    audit.record("auth.email_verified", actor=user, object_type="user", object_id=user.id, ip=client_ip(request))
    return {"ok": True, "message": "Email verified. You can now sign in."}


@router.post("/resend-verification", dependencies=[Depends(limit_auth)])
def resend_verification(body: S.EmailOnlyRequest, request: Request, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(func.lower(User.email) == body.email.strip().lower())).scalar_one_or_none()
    if user is None or user.email_verified:
        return {"ok": True, "message": "If registration is pending, a new verification email has been sent."}
    _send_code(db, user, "verify_email")
    return {"ok": True, "message": "A new verification code has been sent."}


@router.post("/password-reset/request", dependencies=[Depends(limit_auth)])
def request_password_reset(body: S.EmailOnlyRequest, request: Request, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(func.lower(User.email) == body.email.strip().lower())).scalar_one_or_none()
    if user is not None and user.email_verified and user.status == "active":
        try:
            _send_code(db, user, "reset_password")
        except ApiError:
            db.rollback()  # cooldown or delivery failure: respond identically so account existence is not revealed
    return {"ok": True, "message": "If an eligible account exists, a password reset code has been sent."}


@router.post("/password-reset/confirm", dependencies=[Depends(limit_auth)])
def confirm_password_reset(body: S.PasswordResetComplete, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(func.lower(User.email) == body.email.strip().lower())).scalar_one_or_none()
    if user is None or not user.email_verified or not _consume_code(db, user, "reset_password", body.code):
        db.commit()
        raise ApiError(400, "invalid_or_expired_code", "This reset code is invalid or expired. Request a new code.")
    user.password_hash = sec.hash_password(body.new_password)
    db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc)))
    db.commit()
    response.delete_cookie(get_settings().cookie_name, path="/")
    audit.record("auth.password_reset", actor=user, object_type="user", object_id=user.id, ip=client_ip(request))
    return {"ok": True, "message": "Password updated. Please sign in with your new password."}


@router.post("/registration/recovery-link", dependencies=[Depends(limit_auth)])
def registration_recovery_link(body: S.RecoveryLinkRequest, request: Request, db: Session = Depends(get_db)):
    try:
        claims = jwt.decode(body.token, get_settings().secret_key, algorithms=["HS256"],
            options={"require": ["exp", "sub", "purpose"]})
    except jwt.PyJWTError:
        raise ApiError(400, "recovery_link_invalid", "This registration link is invalid or has expired. Request a new verification email.")
    if claims.get("purpose") != "registration_recovery":
        raise ApiError(400, "recovery_link_invalid", "This registration link is invalid or has expired.")
    try:
        user_id = uuid.UUID(claims["sub"])
    except (ValueError, TypeError, AttributeError):
        raise ApiError(400, "recovery_link_invalid", "This registration link is invalid or has expired.")
    user = db.get(User, user_id)
    if user is None or user.email_verified:
        raise ApiError(400, "recovery_link_invalid", "This registration link is no longer valid.")
    code = _issue_code(db, user, "verify_email", force=True)
    db.commit()
    if not mail.send_code(user.email, user.display_name, code, "verify_email", get_settings().email_code_ttl_minutes):
        raise ApiError(503, "email_delivery_unavailable", "We could not send a new verification code. Please try again.")
    return {"ok": True, "email": user.email, "message": "A fresh verification code has been sent."}


def send_due_registration_reminders(db: Session, limit: int = 100) -> int:
    """Called by the scheduled worker/cron. Durable DB schedule makes retries safe."""
    now = datetime.now(timezone.utc)
    rows = db.execute(select(RegistrationReminder).where(RegistrationReminder.sent_at.is_(None),
        RegistrationReminder.cancelled_at.is_(None), RegistrationReminder.due_at <= now)
        .order_by(RegistrationReminder.due_at).limit(limit).with_for_update(skip_locked=True)).scalars().all()
    sent = 0
    for reminder in rows:
        user = db.get(User, reminder.user_id)
        if user is None or user.email_verified or user.status != "active":
            reminder.cancelled_at = now
            continue
        token = jwt.encode({"sub": str(user.id), "purpose": "registration_recovery",
            "iat": now, "exp": now + timedelta(days=7)}, get_settings().secret_key, algorithm="HS256")
        link = get_settings().public_app_url.rstrip("/") + "/verify-email?recovery=" + token
        if mail.send_registration_reminder(user.email, user.display_name, link):
            reminder.sent_at = now
            sent += 1
    db.commit()
    return sent
