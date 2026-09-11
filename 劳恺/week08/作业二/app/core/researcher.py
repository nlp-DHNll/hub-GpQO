"""研究主循环 —— 规划 → 多轮检索 → 综合生成报告。

设计要点：
- 手写 Python 异步循环，调用 LLM / Bocha 客户端完成各阶段（README §1.3）。
- Prompt 模板集中在 app/report/templates.py，渲染函数在 app/report/renderer.py。
- 单次失败由 DeepSeek / Bocha 内部重试；整轮失败则跳过该轮并在 confidence_notes 标注。
- 全局异常被兜底捕获，置任务为 FAILED 并把已收集的 process 落盘。
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

from app.core.task_store import get_task_store
from app.llm.deepseek import DeepSeekClient, DeepSeekError, get_deepseek
from app.models import (
    ProcessRecord,
    ResearchReport,
    ResearchRequest,
    SearchResult,
    SearchRound,
    Source,
    SubQuestion,
    TaskStatus,
)
from app.report.renderer import (
    append_sources_section,
    build_report_header,
    format_sources_for_prompt,
)
from app.report.templates import GAP_PROMPT, PLAN_PROMPT, SYNTHESIS_PROMPT
from app.search.bocha import BochaClient, BochaError, get_bocha


# ============================================================
# 配置
# ============================================================

@dataclass
class ResearchConfig:
    """研究深度参数（request 可覆盖 env 默认值）。"""
    max_rounds: int
    num_subquestions: int
    results_per_query: int


def load_config(request: ResearchRequest) -> ResearchConfig:
    return ResearchConfig(
        max_rounds=request.max_rounds
        or int(os.getenv("DEFAULT_MAX_ROUNDS", "2")),
        num_subquestions=request.num_subquestions
        or int(os.getenv("DEFAULT_NUM_SUBQUESTIONS", "3")),
        results_per_query=int(os.getenv("DEFAULT_RESULTS_PER_QUERY", "5")),
    )


# ============================================================
# 阶段函数
# ============================================================

async def plan_subquestions(
    llm: DeepSeekClient, topic: str, num: int
) -> list[SubQuestion]:
    """规划：把主题拆成 num 个子问题。"""
    prompt = PLAN_PROMPT.format(topic=topic, num_subquestions=num)

    # LLM 输出形如 [{"question": ..., "rationale": ...}, ...]
    raw = await llm.chat_json(prompt, system="你是研究规划助手。")
    items = raw if isinstance(raw, list) else raw.get("items", [])
    result: list[SubQuestion] = []
    for item in items:
        try:
            result.append(
                SubQuestion(
                    question=str(item.get("question", "")).strip(),
                    rationale=item.get("rationale"),
                )
            )
        except Exception:
            continue
    # 容错：万一 LLM 输出不够，降级到 num 个
    while len(result) < num:
        result.append(
            SubQuestion(question=f"{topic} 的关键方面 {len(result)+1}", rationale=None)
        )
    return result[:num]


async def search_round(
    bocha: BochaClient,
    queries: list[str],
    count_per_query: int,
    *,
    round_num: int,
    note: str | None = None,
) -> SearchRound:
    """一轮检索：并行执行多个 query，返回 SearchRound。

    整轮零结果时设置 note="整轮检索未返回任何结果"。
    """
    if not queries:
        return SearchRound(round=round_num, queries=[], results=[], note="无 query 需检索")

    # 并行调用
    tasks = [bocha.search(q, count=count_per_query) for q in queries]
    results_per_query = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[SearchResult] = []
    failures: list[str] = []
    for q, res in zip(queries, results_per_query):
        if isinstance(res, BochaError):
            failures.append(q)
            continue
        if isinstance(res, Exception):
            failures.append(q)
            continue
        all_results.extend(res)

    final_note = note or ""
    if failures:
        failed_note = f"{len(failures)} 个 query 失败"
        final_note = f"{final_note}；{failed_note}" if final_note else failed_note
    if not all_results:
        no_result_note = "整轮检索未返回任何结果"
        final_note = f"{final_note}；{no_result_note}" if final_note else no_result_note

    return SearchRound(
        round=round_num,
        queries=queries,
        results=all_results,
        note=final_note or None,
    )


async def find_gaps(
    llm: DeepSeekClient,
    topic: str,
    subquestions: list[SubQuestion],
    last_round: SearchRound,
) -> list[str]:
    """第 2 轮：分析信息缺口，生成补充 query。"""
    if not last_round.results:
        return []

    subquestions_text = "\n".join(f"- {sq.question}" for sq in subquestions)
    summaries_text = "\n".join(
        f"- [{r.source or r.url}] {r.title}：{r.summary[:300]}"
        for r in last_round.results[:15]  # 限制长度避免超 token
    )

    prompt = GAP_PROMPT.format(
        topic=topic,
        subquestions_text=subquestions_text,
        summaries_text=summaries_text,
    )

    try:
        raw = await llm.chat_json(prompt, system="你是研究规划助手。")
    except DeepSeekError:
        return []

    if isinstance(raw, list):
        return [str(q).strip() for q in raw if str(q).strip()][:3]
    if isinstance(raw, dict):
        return [str(q).strip() for q in raw.get("queries", []) if str(q).strip()][:3]
    return []


def build_sources(rounds: list[SearchRound]) -> list[Source]:
    """跨轮次去重收集来源，按出现顺序编号。"""
    seen: set[str] = set()
    sources: list[Source] = []
    for rnd in rounds:
        for r in rnd.results:
            if r.url in seen:
                continue
            seen.add(r.url)
            sources.append(
                Source(
                    id=len(sources) + 1,
                    title=r.title,
                    url=r.url,
                    snippet=r.summary[:200] if r.summary else None,
                )
            )
    return sources


async def synthesize_report(
    llm: DeepSeekClient,
    topic: str,
    subquestions: list[SubQuestion],
    sources: list[Source],
) -> str:
    """综合：调用 LLM 生成 5 节 Markdown 报告。"""
    subquestions_text = "\n".join(f"- {sq.question}" for sq in subquestions)
    sources_text = format_sources_for_prompt(sources)

    prompt = SYNTHESIS_PROMPT.format(
        topic=topic,
        subquestions_text=subquestions_text,
        sources_text=sources_text,
    )
    return await llm.chat(prompt, system="你是专业中文研究员，输出严谨带引用的报告。")


# ============================================================
# 主入口
# ============================================================

async def run_research(task_id: str) -> None:
    """执行一次完整研究流程。出错时把任务置 FAILED 并保存已收集的 process。"""
    store = get_task_store()
    llm = get_deepseek()
    bocha = get_bocha()

    task = store.get_task(task_id)
    if task is None:
        raise ValueError(f"task {task_id} not found")

    cfg = load_config(task.request)
    process = ProcessRecord()
    start = time.time()

    try:
        # ---------- 1. 规划 ----------
        await store.update_task(
            task_id,
            status=TaskStatus.RUNNING,
            progress="规划子问题",
        )
        subquestions = await plan_subquestions(llm, task.topic, cfg.num_subquestions)
        process.subquestions = subquestions

        # ---------- 2. 第 1 轮 ----------
        await store.update_task(
            task_id,
            progress=f"第 1 轮检索中 (0/{len(subquestions)} 子问题)",
        )
        queries_r1 = [sq.question for sq in subquestions]
        round1 = await search_round(
            bocha, queries_r1, cfg.results_per_query, round_num=1
        )
        process.rounds.append(round1)

        await store.update_task(
            task_id,
            progress=(
                f"第 1 轮完成 ({len(round1.results)} 条结果)"
                + ("；第 1 轮无结果" if not round1.results else "")
            ),
            process=process,
        )

        # ---------- 3. 第 2 轮（信息缺口补检） ----------
        round2_failed = False
        if cfg.max_rounds >= 2:
            await store.update_task(
                task_id, progress="分析信息缺口"
            )
            gap_queries = await find_gaps(
                llm, task.topic, subquestions, round1
            )

            if gap_queries:
                await store.update_task(
                    task_id,
                    progress=f"第 2 轮检索中 ({len(gap_queries)} 个补充 query)",
                )
                round2 = await search_round(
                    bocha,
                    gap_queries,
                    cfg.results_per_query,
                    round_num=2,
                    note="基于信息缺口分析",
                )
                process.rounds.append(round2)
                if not round2.results:
                    round2_failed = True
            else:
                # 无缺口也写一个空 round 记录
                process.rounds.append(
                    SearchRound(
                        round=2,
                        queries=[],
                        results=[],
                        note="LLM 判断信息已充分，无需补检",
                    )
                )

        # ---------- 4. 综合 ----------
        await store.update_task(task_id, progress="综合生成报告")
        sources = build_sources(process.rounds)

        confidence_notes = None
        if not round1.results:
            confidence_notes = "第 1 轮检索未返回任何结果，报告内容可能不完整。"
        elif round2_failed:
            confidence_notes = "第 2 轮补检未返回新结果，部分信息可能不完整。"

        llm_markdown = await synthesize_report(
            llm, task.topic, subquestions, sources
        )

        # 组装完整报告（加元信息头 + 来源列表）
        report_markdown = (
            build_report_header(
                topic=task.topic,
                created_at=task.created_at,
                rounds_count=len(process.rounds),
                sources_count=len(sources),
            )
            + llm_markdown
        )
        report_markdown = append_sources_section(report_markdown, sources)

        process.duration_seconds = round(time.time() - start, 2)
        process.total_results = sum(len(r.results) for r in process.rounds)

        report = ResearchReport(
            topic=task.topic,
            markdown=report_markdown,
            sources=sources,
            confidence_notes=confidence_notes,
        )

        # 落盘报告
        store.save_report_markdown(task_id, report_markdown)

        await store.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress="完成",
            report=report,
            process=process,
        )

    except Exception as e:
        # 把已收集的过程落盘，方便排查
        process.duration_seconds = round(time.time() - start, 2)
        process.total_results = sum(len(r.results) for r in process.rounds)
        try:
            await store.update_task(
                task_id,
                status=TaskStatus.FAILED,
                error=f"{type(e).__name__}: {e}",
                progress=f"失败：{str(e)[:100]}",
                process=process,
            )
        except Exception:
            pass
        raise
