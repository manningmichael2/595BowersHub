"""
Rate limiting middleware: token bucket per user.
"""

import time
import logging
from typing import Dict, Tuple

from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)


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
    }

    def __init__(self):
        # user_id → action → TokenBucket
        self._buckets: Dict[int, Dict[str, TokenBucket]] = {}

    def check(self, user_id: int, action: str = "api_call") -> bool:
        """
        Check if a user is within rate limits for an action.
        Returns True if allowed, raises HTTPException if rate limited.
        """
        if action not in self.LIMITS:
            return True

        max_tokens, window = self.LIMITS[action]

        if user_id not in self._buckets:
            self._buckets[user_id] = {}

        if action not in self._buckets[user_id]:
            self._buckets[user_id][action] = TokenBucket(max_tokens, window)

        bucket = self._buckets[user_id][action]
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
        for user_id, actions in self._buckets.items():
            all_old = all(b.last_refill < cutoff for b in actions.values())
            if all_old:
                to_remove.append(user_id)
        for uid in to_remove:
            del self._buckets[uid]


# Global rate limiter instance
rate_limiter = RateLimiter()
