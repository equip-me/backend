import time


class RateLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._window_start = time.monotonic()
        self._count = 0

    def allow(self) -> bool:
        now = time.monotonic()
        if now - self._window_start >= 60:
            self._window_start = now
            self._count = 0
        if self._count >= self._max:
            return False
        self._count += 1
        return True
