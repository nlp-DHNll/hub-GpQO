# -*- coding: utf-8 -*-
"""有预算、可取消、可观察的深度研究循环。"""
from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from . import config, tools
from .agent.judge import JudgeAgent
from .agent.keyword import KeywordAgent
from .agent.report import ReportAgent
from .agent.summary import SummaryAgent
from .models import (
    ConfidenceNote, DeepResearchResult, DraftBlock, ProcessStep, ResearchLimits,
    ResearchProcess, ResearchRequest, Source, UsageCounters,
)


class ResearchCancelled(Exception):
    pass


Progress = Callable[[dict], Awaitable[None] | None]
Cancelled = Callable[[], bool]


class DeepResearch:
    def __init__(self, request: ResearchRequest, limits: ResearchLimits):
        self.request = request
        self.topic = self._contextual_topic(request)
        self.limits = limits
        self.keyword_agent = KeywordAgent()
        self.summary_agent = SummaryAgent()
        self.judge_agent = JudgeAgent()
        self.report_agent = ReportAgent()

    @staticmethod
    def _contextual_topic(req: ResearchRequest) -> str:
        details = [f"研究主题：{req.topic}", f"研究目标：{req.goal or '形成客观、可追溯的综合判断'}",
                   f"时间范围：{req.date_range}", f"地区：{req.region}", f"报告受众：{req.audience}"]
        if req.follow_up:
            details.append(f"补充研究要求：{req.follow_up}")
        return "\n".join(details)

    async def run(self, on_progress: Progress | None = None, is_cancelled: Cancelled | None = None) -> DeepResearchResult:
        started = time.monotonic()
        process, draft, sources = ResearchProcess(), [], []
        usage = UsageCounters()
        seen_urls: set[str] = set()
        all_dates: list[str] = []
        limited = False
        limit_reason = ""

        self._check_cancel(is_cancelled)
        initial = await self.keyword_agent.generate_keywords(self.topic)
        usage.model_calls += 1
        initial = (initial or [self.request.topic])[: self.limits.max_searches]
        process.plan = initial
        process.steps.append(self._step("plan", 0, {"keywords": initial}))
        await self._progress(on_progress, process, draft, sources, usage, 8, "研究规划已完成")

        searched: list[str] = []
        todo = initial
        for round_no in range(1, self.limits.max_rounds + 1):
            process.iterations = round_no
            for keyword in todo:
                self._check_cancel(is_cancelled)
                reason = self._budget_reason(started, usage, reserve_model_calls=2)
                if reason:
                    limited, limit_reason = True, reason
                    break
                if keyword in searched:
                    continue
                searched.append(keyword)
                process.search_queries.append(keyword)
                try:
                    results = await tools.web_search(keyword)
                except Exception as exc:  # 单次搜索失败时继续，以摘要/已有资料生成
                    results = []
                    process.steps.append(self._step("warning", round_no, {"keyword": keyword, "error": str(exc)[:200]}))
                usage.searches += 1
                self._collect_sources(results, seen_urls, sources, process, all_dates)
                process.steps.append(self._step("search", round_no, {"keyword": keyword, "results": len(results)}))
                await self._progress(on_progress, process, draft, sources, usage,
                                     min(70, 10 + int(55 * usage.searches / self.limits.max_searches)), f"正在整理：{keyword}")

                self._check_cancel(is_cancelled)
                text = await self.summary_agent.summarize(self.topic, keyword, results)
                usage.model_calls += 1
                draft.append(DraftBlock(round=round_no, keyword=keyword, text=(text or "资料不足，未能形成有来源支持的正文。")))
                process.steps.append(self._step("summarize", round_no, {"keyword": keyword, "chars": len(text or "")}))
                await self._progress(on_progress, process, draft, sources, usage,
                                     min(76, 18 + int(55 * usage.searches / self.limits.max_searches)), f"已完成：{keyword}")
            if limited:
                break

            self._check_cancel(is_cancelled)
            if usage.model_calls + 2 > self.limits.max_model_calls:
                limited, limit_reason = True, "达到模型调用上限"
                break
            decision = await self.judge_agent.judge(self.topic, self._join_draft(draft), sources, searched)
            usage.model_calls += 1
            process.steps.append(self._step("judge", round_no, decision.model_dump()))
            await self._progress(on_progress, process, draft, sources, usage, 80, "资料充分性判断完成")
            if decision.sufficient:
                break
            todo = [word for word in decision.new_keywords if word not in searched]
            if not todo:
                break

        self._check_cancel(is_cancelled)
        if not draft:
            draft.append(DraftBlock(round=0, keyword="资料缺口", text="检索未返回足够公开资料，以下结论仅供参考。"))
        confidence = self._confidence(sources, draft, all_dates, limited, limit_reason)
        report, html = await self.report_agent.generate(self.topic, draft, sources, confidence)
        usage.model_calls += 2
        usage.elapsed_seconds = int(time.monotonic() - started)
        return DeepResearchResult(report=report, report_html=html, sources=sources, draft=draft,
                                  process=process, confidence=confidence, usage=usage,
                                  limited=limited, limit_reason=limit_reason)

    def _budget_reason(self, started: float, usage: UsageCounters, reserve_model_calls: int = 0) -> str:
        if time.monotonic() - started >= self.limits.max_seconds:
            return "达到最长研究时间"
        if usage.searches >= self.limits.max_searches:
            return "达到最大搜索次数"
        if usage.model_calls + reserve_model_calls >= self.limits.max_model_calls:
            return "达到模型调用上限"
        return ""

    @staticmethod
    def _check_cancel(callback: Cancelled | None) -> None:
        if callback and callback():
            raise ResearchCancelled()

    @staticmethod
    def _step(kind: str, round_no: int, detail: dict) -> ProcessStep:
        return ProcessStep(type=kind, round=round_no, detail=detail, created_at=datetime.now(timezone.utc).isoformat())

    @staticmethod
    async def _progress(callback: Progress | None, process: ResearchProcess, draft: list[DraftBlock],
                        sources: list[Source], usage: UsageCounters, progress: int, current_step: str) -> None:
        if callback is None:
            return
        value = callback({"process": process.model_dump(), "draft": [b.model_dump() for b in draft],
                          "sources": [s.model_dump() for s in sources], "usage": usage.model_dump(),
                          "progress": progress, "current_step": current_step})
        if inspect.isawaitable(value):
            await value

    @staticmethod
    def _collect_sources(results: list[dict], seen: set[str], sources: list[Source],
                         process: ResearchProcess, dates: list[str]) -> None:
        for item in results:
            url = (item.get("url") or "").strip()
            if url and url not in seen:
                seen.add(url)
                process.reviewed_urls.append(url)
                sources.append(Source(url=url, title=item.get("title") or "", site_name=item.get("site_name") or "",
                                      snippet=(item.get("content") or item.get("snippet") or "")[:1000],
                                      accessed_at=config.today_str(), published_at=item.get("date") or "",
                                      extraction_status=item.get("extraction_status") or "summary"))
            if url:
                for index, source in enumerate(sources, 1):
                    if source.url == url:
                        item["citation"] = f"[{index}]"
                        break
            if item.get("date"):
                dates.append(item["date"])

    @staticmethod
    def _join_draft(draft: list[DraftBlock]) -> str:
        return "\n\n".join(f"【{b.keyword}】\n{b.text}" for b in draft)

    @staticmethod
    def _confidence(sources: list[Source], draft: list[DraftBlock], dates: list[str], limited: bool, reason: str) -> ConfidenceNote:
        full = sum(source.extraction_status == "full" for source in sources)
        overall = "high" if len(sources) >= 12 and full >= 4 else "medium" if len(sources) >= 5 else "low"
        gaps = []
        if limited:
            gaps.append(reason)
        if full == 0:
            gaps.append("未能提取网页全文，分析主要基于搜索摘要")
        notes = [f"共使用 {len(sources)} 个去重来源，其中 {full} 个成功提取正文。", "无可追溯来源的判断必须视为模型推断。"]
        return ConfidenceNote(overall=overall, info_cutoff=max([d[:10] for d in dates if d] or [config.today_str()]), notes=notes, gaps=gaps)


if __name__ == "__main__":
    print("engine 模块加载成功")
