"""Unit tests for the in-memory login rate limiter."""

from app.auth.rate_limit import LoginRateLimiter


class FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_limiter(clock: FakeClock) -> LoginRateLimiter:
    return LoginRateLimiter(max_failures=3, window_seconds=60, clock=clock)


def test_allows_until_max_failures_reached():
    clock = FakeClock()
    limiter = make_limiter(clock)
    for _ in range(2):
        limiter.record_failure("ip")
    assert limiter.retry_after_seconds("ip") == 0
    limiter.record_failure("ip")
    assert limiter.retry_after_seconds("ip") == 60


def test_retry_after_counts_down_and_window_expires():
    clock = FakeClock()
    limiter = make_limiter(clock)
    for _ in range(3):
        limiter.record_failure("ip")
    clock.now += 45.5
    assert limiter.retry_after_seconds("ip") == 15
    clock.now += 15
    assert limiter.retry_after_seconds("ip") == 0


def test_keys_are_independent():
    limiter = make_limiter(FakeClock())
    for _ in range(3):
        limiter.record_failure("a")
    assert limiter.retry_after_seconds("b") == 0


def test_reset_clears_failures():
    limiter = make_limiter(FakeClock())
    for _ in range(3):
        limiter.record_failure("ip")
    limiter.reset("ip")
    assert limiter.retry_after_seconds("ip") == 0
