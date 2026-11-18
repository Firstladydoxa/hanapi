"""Password hashing (argon2id), JWT session cookie and CSRF tokens."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..config import get_settings

_hasher = PasswordHasher()
# Used to burn comparable time when the account does not exist (avoids user enumeration by timing).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))
ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def generate_password() -> str:
    return secrets.token_urlsafe(18)


def create_session_token(user_id: uuid.UUID) -> Tuple[str, str, datetime]:
    s = get_settings()
    jti = secrets.token_hex(16)
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=s.session_ttl_minutes)
    token = jwt.encode({"sub": str(user_id), "jti": jti, "iat": now, "exp": exp}, s.secret_key, algorithm=ALGORITHM)
    return token, jti, exp


def decode_session_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM], options={"require": ["exp", "sub", "jti"]})
    except jwt.PyJWTError:
        return None


def csrf_for(jti: str) -> str:
    """CSRF token bound to the session (HMAC of the session id); sent back in X-CSRF-Token."""
    return hmac.new(get_settings().secret_key.encode(), f"csrf:{jti}".encode(), hashlib.sha256).hexdigest()


def csrf_valid(jti: str, supplied: Optional[str]) -> bool:
    return bool(supplied) and hmac.compare_digest(csrf_for(jti), supplied or "")
