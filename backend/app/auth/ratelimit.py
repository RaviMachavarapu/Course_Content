"""Fixed-window rate limiting on Redis.

Used for login (spec.md §3.1/§3.7: "rate-limited after N attempts"). A window is
a single counter key with a TTL; the first hit in a window sets the expiry.
"""

from __future__ import annotations

import re

import redis
from starlette.requests import Request

_SPEC_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*([smh])\s*$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def parse_rate(spec: str) -> tuple[int, int]:
    """``"10/5m"`` -> ``(10, 300)``  (limit, window_seconds)."""
    m = _SPEC_RE.match(spec)
    if not m:
        raise ValueError(f"invalid rate spec: {spec!r}")
    limit, qty, unit = int(m.group(1)), int(m.group(2)), m.group(3)
    return limit, qty * _UNIT_SECONDS[unit]


def client_ip(request: Request) -> str:
    """The caller's IP. uvicorn runs with proxy headers trusting only the nginx
    container, so `request.client.host` is already the real client address
    (never a client-supplied X-Forwarded-For)."""
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self, client: redis.Redis[str]) -> None:
        self._r = client

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Register one hit. Returns True if still within the limit."""
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        count, _ = pipe.execute()
        return int(count) <= limit

    def peek(self, key: str) -> int:
        raw = self._r.get(key)
        return int(raw) if raw is not None else 0

    def reset(self, key: str) -> None:
        self._r.delete(key)
