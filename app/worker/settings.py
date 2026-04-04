from typing import Any, ClassVar, Protocol, cast

from arq import create_pool, func
from arq.connections import ArqRedis, RedisSettings
from arq.cron import cron
from arq.typing import WorkerCoroutine

from app.core.config import get_settings


class WorkerSettingsClass(Protocol):
    """Protocol describing the class returned by _build_worker_settings."""

    functions: ClassVar[list[Any]]
    cron_jobs: ClassVar[list[Any]]
    redis_settings: ClassVar[RedisSettings]


async def get_arq_pool() -> ArqRedis:
    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.worker.redis_url)
    return await create_pool(redis_settings)


def _build_worker_settings() -> type[WorkerSettingsClass]:
    """Build WorkerSettings class with all functions and crons aggregated."""
    from app.worker.chat import notify_new_chat_message
    from app.worker.media import cleanup_orphans_cron, process_media_job
    from app.worker.orders import activate_order, expire_order, finish_order, order_sweep_cron

    class WorkerSettings:
        functions: ClassVar[list[Any]] = [
            func(cast("WorkerCoroutine", process_media_job), max_tries=3),
            func(cast("WorkerCoroutine", notify_new_chat_message), max_tries=1),
            func(cast("WorkerCoroutine", expire_order), max_tries=3),
            func(cast("WorkerCoroutine", activate_order), max_tries=3),
            func(cast("WorkerCoroutine", finish_order), max_tries=3),
        ]
        cron_jobs: ClassVar[list[Any]] = [
            cron(cast("WorkerCoroutine", cleanup_orphans_cron), minute={0}),
            cron(cast("WorkerCoroutine", order_sweep_cron), hour={3}, minute={0}),
        ]
        max_jobs = get_settings().worker.max_concurrent_jobs
        redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(get_settings().worker.redis_url)

    return WorkerSettings
