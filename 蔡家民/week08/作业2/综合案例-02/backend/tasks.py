"""Celery Worker 入口。"""
from __future__ import annotations

import asyncio

from celery import Celery

from . import config
from .research import run_research

celery_app = Celery("deep_research", broker=config.REDIS_URL, backend=config.REDIS_URL)
celery_app.conf.update(task_track_started=True, worker_prefetch_multiplier=1, task_acks_late=True)


@celery_app.task(name="research.run", autoretry_for=(), acks_late=True)
def run_research_task(research_id: str) -> None:
    asyncio.run(run_research(research_id))
