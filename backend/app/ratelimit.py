"""Small in-process sliding-window rate limiter (per worker process).

Good enough for a single-instance pilot. For multiple workers/instances put a shared limiter
(e.g. Redis-backed or at the reverse proxy) in front; this is documented in the README.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Request

from .config import get_settings
from .errors import ApiError

_lock = threading.Lock()
_hits: Dict[str, Deque[float]] = defaultdict(deque)
WINDOW_S = 60.0


def reset() -> None:
    with _lock:
        _hits.clear()


def hit(key: str, limit: int) -> bool:
    """Record a hit; False when over the limit. limit <= 0 disables the limiter."""
    if limit <= 0:
        return True
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > WINDOW_S:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def enforce(bucket: str, key: str, limit: int) -> None:
    if not hit(f"{bucket}:{key}", limit):
        raise ApiError(429, "rate_limited", "Too many requests. Please wait a moment and try again.", headers={"Retry-After": "30"})


def limit_auth(request: Request) -> None:
    from .deps import client_ip

    enforce("auth", client_ip(request), get_settings().rate_limit_auth_per_min)
