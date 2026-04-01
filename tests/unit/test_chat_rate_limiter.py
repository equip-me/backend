from unittest.mock import patch

from app.chat.websocket import RateLimiter


class TestRateLimiter:
    def test_allows_under_limit(self) -> None:
        limiter = RateLimiter(max_per_minute=5)
        for _ in range(5):
            assert limiter.allow() is True

    def test_blocks_over_limit(self) -> None:
        limiter = RateLimiter(max_per_minute=3)
        for _ in range(3):
            assert limiter.allow() is True
        assert limiter.allow() is False

    def test_resets_after_window(self) -> None:
        limiter = RateLimiter(max_per_minute=2)
        assert limiter.allow() is True
        assert limiter.allow() is True
        assert limiter.allow() is False

        with patch("time.monotonic", return_value=limiter._window_start + 61):
            assert limiter.allow() is True
