# -*- coding: utf-8 -*-
"""研究编排：后台执行、中间结果逐步落盘与最终落盘。

完整的 agent 流水线封装在 engine.py 的 DeepResearch 里；本模块只负责把它接到
存储层：
- 每完成一轮通过 on_progress 回调把 process / draft / sources 写盘（status 保持
  running），轮询即可实时看到中间结果；
- 全部完成后组装最终 ResearchRecord 落盘为 completed；
- 任何异常把记录标记为 failed，并保留已写入的中间结果。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import storage
from .engine import DeepResearch
from .models import DraftBlock, ResearchProcess, Source, Status

logger = logging.getLogger(__name__)


async def run_research(research_id: str, topic: str) -> None:
    """后台任务主体：running -> completed / failed，逐步保存中间结果。"""
    logger.info("研究开始: %s | %s", research_id, topic)
    try:
        storage.update_status(research_id, "running")

        async def on_progress(snapshot: dict) -> None:
            rec = storage.get(research_id)
            if rec is None:
                return
            rec.updated_at = datetime.now(timezone.utc).isoformat()
            rec.process = ResearchProcess.model_validate(snapshot["process"])
            rec.draft = [DraftBlock.model_validate(b) for b in snapshot["draft"]]
            rec.sources = [Source.model_validate(s) for s in snapshot["sources"]]
            storage.save(rec)  # status 保持 running

        result = await DeepResearch(topic).run(on_progress=on_progress)

        rec = storage.get(research_id)
        if rec is None:
            return
        rec.status = Status.completed
        rec.updated_at = datetime.now(timezone.utc).isoformat()
        rec.report = result.report
        rec.report_html = result.report_html
        rec.sources = result.sources
        rec.draft = result.draft
        rec.process = result.process
        rec.confidence = result.confidence
        storage.save(rec)
        logger.info(
            "研究完成: %s（分节 %d 篇、来源 %d 个）",
            research_id,
            len(result.report.sections),
            len(result.sources),
        )
    except Exception as exc:  # noqa: BLE001 - 任何异常都记到记录里
        logger.exception("研究失败: %s", research_id)
        storage.update_status(research_id, "failed", error=str(exc))


if __name__ == "__main__":
    # 测试 demo：完整跑一次研究并打印结果（需要密钥与网络）
    import asyncio
    import logging
    import uuid

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")

    async def _demo() -> None:
        topic = "2026 年主流 Agent 框架对比"
        research_id = uuid.uuid4().hex
        storage.create(research_id, topic)
        print(f"开始研究: {research_id} | {topic}")

        await run_research(research_id, topic)

        rec = storage.get(research_id)
        assert rec is not None
        print("status:", rec.status)
        if rec.status == Status.completed and rec.report is not None:
            print("标题:", rec.report.title)
            print("分节:", len(rec.report.sections), "| 关键结论:", len(rec.report.key_conclusions))
            print("来源:", len(rec.sources), "| 置信度:", rec.confidence.overall if rec.confidence else None)
            print("HTML 长度:", len(rec.report_html))
            print("过程 steps:", len(rec.process.steps) if rec.process else 0)
        else:
            print("error:", rec.error)

    asyncio.run(_demo())
