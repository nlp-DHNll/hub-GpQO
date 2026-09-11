# -*- coding: utf-8 -*-
"""后台研究执行器：保存每个步骤，支持取消、限制与友好失败。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import storage
from .engine import DeepResearch, ResearchCancelled
from .models import DraftBlock, ResearchProcess, ResearchRequest, Source, Status, UsageCounters

logger = logging.getLogger(__name__)


async def run_research(research_id: str) -> None:
    rec = storage.get(research_id)
    if rec is None or rec.status not in {Status.queued, Status.pending}:
        return
    rec.status = Status.running
    rec.started_at = datetime.now(timezone.utc).isoformat()
    rec.current_step = "正在规划研究"
    rec.progress = 3
    rec.error = None
    rec.friendly_error = None
    storage.save(rec)

    request = ResearchRequest(
        topic=rec.topic, goal=rec.goal, date_range=rec.date_range, region=rec.region,
        audience=rec.audience, depth=rec.depth, parent_id=rec.parent_id, follow_up=rec.follow_up,
    )

    async def on_progress(snapshot: dict) -> None:
        current = storage.get(research_id)
        if current is None:
            return
        current.process = ResearchProcess.model_validate(snapshot["process"])
        current.draft = [DraftBlock.model_validate(item) for item in snapshot["draft"]]
        current.sources = [Source.model_validate(item) for item in snapshot["sources"]]
        current.usage = UsageCounters.model_validate(snapshot["usage"])
        current.progress = snapshot["progress"]
        current.current_step = snapshot["current_step"]
        storage.save(current)

    def is_cancelled() -> bool:
        current = storage.get(research_id)
        return current is None or current.status in {Status.cancelling, Status.cancelled}

    try:
        result = await DeepResearch(request, rec.limits).run(on_progress=on_progress, is_cancelled=is_cancelled)
        rec = storage.get(research_id)
        if rec is None:
            return
        rec.status = Status.completed
        rec.completed_at = datetime.now(timezone.utc).isoformat()
        rec.current_step = "报告已完成"
        rec.progress = 100
        rec.report, rec.report_html = result.report, result.report_html
        rec.sources, rec.draft, rec.process = result.sources, result.draft, result.process
        rec.confidence, rec.usage = result.confidence, result.usage
        rec.limited, rec.limit_reason = result.limited, result.limit_reason
        storage.save(rec)
    except ResearchCancelled:
        rec = storage.get(research_id)
        if rec:
            rec.status = Status.cancelled
            rec.current_step = "任务已取消，已保留当前结果"
            rec.completed_at = datetime.now(timezone.utc).isoformat()
            storage.save(rec)
    except Exception as exc:  # noqa: BLE001
        logger.exception("研究失败: %s", research_id)
        storage.update_status(research_id, "failed", str(exc), "研究过程中出现异常，已保留进度，可点击重试。")


if __name__ == "__main__":
    print("research 执行器已就绪")
