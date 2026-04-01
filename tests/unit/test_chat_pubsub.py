import pytest

import app.chat.pubsub as pubsub_module
from app.chat.pubsub import get_redis


class TestGetRedis:
    def test_raises_when_not_initialized(self) -> None:
        original = pubsub_module._redis
        pubsub_module._redis = None
        try:
            with pytest.raises(RuntimeError, match="Redis not initialized"):
                get_redis()
        finally:
            pubsub_module._redis = original
