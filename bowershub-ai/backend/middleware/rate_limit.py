"""
Rate limiting middleware: token bucket per user.
"""

import time
import logging
from typing import Dict, Tuple, Union

from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)

# Rate-limit subjects are keyed by either an authenticated user id (int) or, for
# pre-auth endpoints like login, a client IP string.
Subject = Union[int, str]


def client_ip(request: Request) -> str:
    """Best-effort client IP for rate limiting.

    Honors the first entry of X-Forwarded-For (set by our reverse proxy, Caddy)
    so that per-IP limits apply to the real client rather than the proxy. This
    trusts the proxy to set the header; the app is only reachable through it.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


class TokenBucket:
    """Simple token bucket rate limiter."""

    def __init__(self, max_tokens: int, refill_seconds: float):
        self.max_tokens = max_tokens
        self.refill_seconds = refill_seconds
        self.tokens = max_tokens
        self.last_refill = time.time()

    def consume(self) -> bool:
        """Try to consume a token. Returns True if allowed, False if rate limited."""
        now = time.time()
        elapsed = now - self.last_refill

        # Refill tokens
        refill_amount = elapsed * (self.max_tokens / self.refill_seconds)
        self.tokens = min(self.max_tokens, self.tokens + refill_amount)
        self.last_refill = now

        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

    @property
    def retry_after(self) -> float:
        """Seconds until next token is available."""
        return self.refill_seconds / self.max_tokens


class RateLimiter:
    """Per-user rate limiter with configurable limits per action type."""

    # (max_tokens, refill_window_seconds)
    LIMITS: Dict[str, Tuple[int, float]] = {
        "message": (30, 60.0),       # 30 messages per 60 seconds
        "api_call": (100, 3600.0),   # 100 API calls per hour
        "file_upload": (20, 3600.0), # 20 uploads per hour
        "login": (5, 60.0),          # 5 login attempts per minute, per IP
    }

    def __init__(self):
        # subject (user_id or IP) → action → TokenBucket
        self._buckets: Dict[Subject, Dict[str, TokenBucket]] = {}

    def check(self, subject: Subject, action: str = "api_call") -> bool:
        """
        Check if a subject (user id, or IP for pre-auth actions) is within rate
        limits for an action. Returns True if allowed, raises HTTPException (429)
        if rate limited.
        """
        if action not in self.LIMITS:
            return True

        max_tokens, window = self.LIMITS[action]

        if subject not in self._buckets:
            self._buckets[subject] = {}

        if action not in self._buckets[subject]:
            self._buckets[subject][action] = TokenBucket(max_tokens, window)

        bucket = self._buckets[subject][action]
        if not bucket.consume():
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {action}. Try again in {bucket.retry_after:.0f}s.",
                headers={"Retry-After": str(int(bucket.retry_after))},
            )
        return True

    def cleanup_old_buckets(self):
        """Remove buckets for users who haven't been seen in a while."""
        # Simple cleanup — could be called periodically
        cutoff = time.time() - 7200  # 2 hours
        to_remove = []
        for subject, actions in self._buckets.items():
            all_old = all(b.last_refill < cutoff for b in actions.values())
            if all_old:
                to_remove.append(subject)
        for subject in to_remove:
            del self._buckets[subject]


# Global rate limiter instance
rate_limiter = RateLimiter()
