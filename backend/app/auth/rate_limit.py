"""In-memory brute-force guard for ``POST /api/auth/login``.

Single-process only: state lives in this worker's memory and resets on restart,
which is enough for a single-user app run by one uvicorn worker.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from ..config import settings


class LoginRateLimiter:
    """Track failed logins per key (client IP) inside a sliding window.

    Example:
        >>> limiter = LoginRateLimiter(max_failures=5, window_seconds=900)
        >>> limiter.record_failure("1.2.3.4")
        >>> limiter.retry_after_seconds("1.2.3.4")
        0
    """

    def __init__(
        self,
        max_failures: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        # Sync FastAPI endpoints run in a threadpool, so guard shared state.
        self._lock = threading.Lock()

    def retry_after_seconds(self, key: str) -> int:
        """Return seconds until ``key`` may try again, or 0 if it is allowed now."""
        with self._lock:
            failures = self._prune(key)
            if len(failures) < self.max_failures:
                return 0
            unlock_at = failures[0] + self.window_seconds
            return max(1, math.ceil(unlock_at - self._clock()))

    def record_failure(self, key: str) -> None:
        """Count one failed login attempt for ``key``."""
        with self._lock:
            self._failures.setdefault(key, deque()).append(self._clock())

    def reset(self, key: str) -> None:
        """Forget all failures for ``key`` (called after a successful login)."""
        with self._lock:
            self._failures.pop(key, None)

    def _prune(self, key: str) -> deque[float]:
        failures = self._failures.setdefault(key, deque())
        cutoff = self._clock() - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures


login_rate_limiter = LoginRateLimiter(
    max_failures=settings.login_max_failures,
    window_seconds=settings.login_window_seconds,
)


def get_login_rate_limiter() -> LoginRateLimiter:
    """FastAPI dependency; tests override it with a fresh limiter."""
    return login_rate_limiter


def client_ip(request: Request) -> str:
    """Return the caller's IP, or ``"unknown"`` when the transport hides it."""
    return request.client.host if request.client else "unknown"
