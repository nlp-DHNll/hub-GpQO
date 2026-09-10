"""任务分发：Compose 使用 Celery；本地开发自动回退到并发 2 的 asyncio 队列。"""
from __future__ import annotations

import asyncio

from . import config
from .research import run_research

_semaphore = asyncio.Semaphore(2)


async def _local_job(research_id: str) -> None:
    async with _semaphore:
        await run_research(research_id)


def enqueue(research_id: str) -> None:
    if config.USE_CELERY:
        from .tasks import run_research_task
        run_research_task.delay(research_id)
    else:
        asyncio.create_task(_local_job(research_id))
