import asyncio
from typing import cast

from arq.typing import WorkerSettingsBase
from arq.worker import create_worker

from app.worker.settings import _build_worker_settings

asyncio.set_event_loop(asyncio.new_event_loop())
worker = create_worker(cast("type[WorkerSettingsBase]", _build_worker_settings()))
worker.run()
