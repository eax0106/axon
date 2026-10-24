"""Arq worker.

Run: `arq worker.main.WorkerSettings`. Health: `arq --check worker.main.WorkerSettings`.
"""

import os
from typing import Any

from arq.connections import RedisSettings


async def ping(_ctx: dict[str, Any]) -> str:
    # ponytail: arq refuses a worker with no functions; real jobs replace this from B5 on.
    return "pong"


class WorkerSettings:
    functions = (ping,)
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    health_check_interval = 10
