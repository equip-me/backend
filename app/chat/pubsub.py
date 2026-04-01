import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

logger = logging.getLogger(__name__)

_redis: Redis | None = None


async def init_redis(url: str) -> None:
    global _redis  # noqa: PLW0603
    _redis = Redis.from_url(url, decode_responses=True)
    logger.info("Redis pub/sub client initialized")


async def close_redis() -> None:
    global _redis  # noqa: PLW0603
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis pub/sub client closed")


def get_redis() -> Redis:
    if _redis is None:
        msg = "Redis not initialized — call init_redis() first"
        raise RuntimeError(msg)
    return _redis


async def publish(channel: str, data: dict[str, Any]) -> None:
    redis = get_redis()
    await redis.publish(channel, json.dumps(data))


async def subscribe(channel: str) -> PubSub:
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    return pubsub
