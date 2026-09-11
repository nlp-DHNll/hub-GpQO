"""研究图节点:plan / search / read / reflect / synthesize。

约定:
- 节点返回增量 dict,由 ResearchState 的 reducer 合并
- 细粒度进度事件经 get_stream_writer 发出(stream_mode="custom"),
  非流式调用(invoke)时为 no-op
- 每个节点都有降级路径:异常不中断任务,置 degraded 后继续收敛
"""
import asyncio
import logging
import re
from collections import Counter

from langchain_core.messages import HumanMessage
from langgraph.config import get_stream_writer

from app.config import settings
from app.graph.state import ResearchState
from app.llm import get_llm
from app.schemas import FindingsOutput, PlanOutput, ReflectOutput, SelectOutput
from app.tools.bocha import web_search
from app.tools.fetcher import fetch_page

logger = logging.getLogger(__name__)


def _emit(event: dict) -> None:
    """发进度事件;不在流式上下文时安全跳过。"""
    try:
        get_stream_writer()(event)
    except Exception:
        pass


async def _structured(schema, prompt: str, retry: int = 1):
    """结构化 LLM 调用,失败重试 retry 次后抛出(由调用方降级)。"""
    model = get_llm().with_structured_output(schema)
    last_err: Exception | None = None
    for _ in range(retry + 1):
        try:
            return await model.ainvoke([HumanMessage(content=prompt)])
        except Exception as e:  # 调用/解析失败
            last_err = e
            logger.warning("结构化输出失败(将重试): %s", e)
    raise RuntimeError(f"结构化输出重试耗尽: {last_err}")


# ---------- plan ----------

async def plan_node(state: ResearchState) -> dict:
    """主题拆解为 3~6 个子问题,作为首轮检索查询。"""
    topic = state["topic"]
    try:
        out: PlanOutput = await _structured(
            PlanOutput,
            "你是研究规划专家。请把研究主题拆解为 3~6 个相互独立、"
            "合并起来能完整覆盖主题的子问题,作为后续检索的查询词。\n"
            "子问题语言与主题一致,适合直接作为搜索引擎查询。\n\n"
            f"研究主题:{topic}",
        )
        sub_questions = [q.strip() for q in out.sub_questions if q.strip()]
    except Exception as e:
        logger.warning("plan 降级(以主题本身为查询): %s", e)
        return {"plan": [topic], "pending_queries": [topic], "degraded": True}
    _emit({"type": "plan", "sub_questions": sub_questions})
    return {"plan": sub_questions, "pending_queries": list(sub_questions)}


# ---------- search ----------

async def search_node(state: ResearchState) -> dict:
    """对每条 pending_query 检索;结果跨轮按 URL 去重。"""
    iteration = len(state["rounds"]) + 1
    _emit({"type": "round_start", "round": iteration})

    budget_left = settings.search_budget - state["search_count"]
    queries = [q for q in state["pending_queries"] if q.strip()][: max(budget_left, 0)]
    current: dict = {
        "round": iteration,
        "queries": queries,
        "failed_queries": [],
        "results": [],
        "read_urls": [],
        "findings_added": 0,
    }
    if not queries:  # 预算耗尽或无查询:空轮,交由路由进 synthesize
        return {"current_round": current, "pending_queries": []}

    _emit({"type": "search", "round": iteration, "queries": queries})
    new_results: list[dict] = []
    seen_update: dict[str, bool] = {}
    counted = 0
    try:
        for q in queries:
            rs = await web_search(q)
            if not rs:
                current["failed_queries"].append(q)
                continue
            counted += 1
            for r in rs:
                url = r.get("url", "")
                if not url or url in state["seen_urls"] or url in seen_update:
                    continue
                seen_update[url] = True
                new_results.append(r)
    except Exception as e:  # 防御:web_search 理论不抛
        logger.warning("search 降级: %s", e)
        return {
            "current_round": current,
            "seen_urls": seen_update,
            "search_count": counted,
            "pending_queries": [],
            "degraded": True,
        }
    current["results"] = new_results
    return {
        "current_round": current,
        "seen_urls": seen_update,
        "search_count": counted,
        "pending_queries": [],
    }


# ---------- read ----------

async def read_node(state: ResearchState) -> dict:
    """挑选 ≤6 条 URL → 并发抓取 → 逐页抽取要点;失败以摘要兜底。"""
    current = dict(state["current_round"])
    results: list[dict] = current.get("results", [])
    if not results:
        return {"current_round": current}

    # 1) LLM 挑选高价值 URL(失败降级:取前 N 条)
    listing = "\n".join(
        f"{i + 1}. {r['title']}\n   {r['url']}\n   摘要:{r['summary'][:150]}"
        for i, r in enumerate(results)
    )
    try:
        out: SelectOutput = await _structured(
            SelectOutput,
            "从下列搜索结果中挑选对研究最有价值、信息量最大的页面 URL,"
            f"最多 {settings.max_read_per_round} 条,按价值排序返回:\n\n{listing}\n\n"
            f"研究主题:{state['topic']}",
        )
        valid = {r["url"] for r in results}
        urls = [u for u in out.urls if u in valid][: settings.max_read_per_round]
    except Exception as e:
        logger.warning("URL 挑选降级(取前 %s 条): %s", settings.max_read_per_round, e)
        urls = [r["url"] for r in results[: settings.max_read_per_round]]
        return_degraded = True
    else:
        return_degraded = False
    if not urls:
        return {"current_round": current, "degraded": return_degraded}

    # 2) 并发抓取正文(信号量在 fetcher 内部)
    texts = await asyncio.gather(*(fetch_page(u) for u in urls))
    page_map = dict(zip(urls, texts))

    # 3) 逐页 LLM 抽取要点(并发 ≤ concurrency)
    sem = asyncio.Semaphore(settings.concurrency)
    summary_by_url = {r["url"]: r["summary"] for r in results}

    async def extract_one(url: str, text: str | None) -> list[dict]:
        if text:
            async with sem:
                try:
                    out: FindingsOutput = await _structured(
                        FindingsOutput,
                        "从下面的网页正文中抽取与研究主题相关的事实性要点(3~8 条)。\n"
                        "每条要点必须给出:\n"
                        "- point:要点陈述(与主题相同语言)\n"
                        "- quote:正文中支撑该要点的原文摘录(≤50 字,逐字摘录,不得改写)\n"
                        "- url:固定填入来源 URL\n"
                        "只抽取正文真实出现的信息,不要推断。\n\n"
                        f"研究主题:{state['topic']}\n来源 URL:{url}\n\n正文:\n{text}",
                    )
                    return [
                        {
                            "point": f.point,
                            "quote": f.quote[:50],
                            "url": url,
                            "from_summary": False,
                        }
                        for f in out.findings
                    ]
                except Exception as e:
                    logger.warning("要点抽取失败(摘要兜底) %s: %s", url, e)
        # 摘要兜底:正文缺失或抽取失败
        summary = summary_by_url.get(url, "")
        if not summary:
            return []
        return [
            {
                "point": summary[:200],
                "quote": summary[:50],
                "url": url,
                "from_summary": True,
            }
        ]

    per_page = await asyncio.gather(*(extract_one(u, t) for u, t in page_map.items()))
    findings_new = [f for fs in per_page for f in fs]

    # 4) 来源与轮次记录
    fallback_urls = {u for u, t in page_map.items() if t is None}
    sources_new = {
        r["url"]: {
            "title": r["title"],
            "summary": r["summary"][:300],
            "date_published": r.get("date_published", ""),
            "from_summary": r["url"] in fallback_urls,
        }
        for r in results
        if r["url"] in page_map
    }
    current["read_urls"] = list(page_map)
    current["findings_added"] = len(findings_new)
    _emit(
        {
            "type": "read",
            "round": current["round"],
            "urls": list(page_map),
            "ok": len([u for u, t in page_map.items() if t is not None]),
            "fallback": len(fallback_urls),
        }
    )
    update: dict = {
        "current_round": current,
        "findings": findings_new,
        "sources": sources_new,
    }
    if return_degraded:
        update["degraded"] = True
    return update


# ---------- reflect ----------

async def reflect_node(state: ResearchState) -> dict:
    """对照子问题审视信息缺口,决定继续检索还是收敛。"""
    current = dict(state["current_round"])
    findings_lines = "\n".join(f"- {f['point']}" for f in state["findings"]) or "(暂无)"
    plan_lines = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(state["plan"]))
    searched = {
        q for r in state["rounds"] for q in r.get("queries", [])
    } | set(current.get("queries", []))
    try:
        out: ReflectOutput = await _structured(
            ReflectOutput,
            "你是研究审阅者。对照子问题检查已有研究发现,判断信息是否充分。\n\n"
            f"研究主题:{state['topic']}\n\n子问题:\n{plan_lines}\n\n"
            f"已有研究发现:\n{findings_lines}\n\n"
            "已检索过的查询(不要重复):\n" + ("; ".join(sorted(searched)) or "(无)") +
            "\n\n请输出:\n"
            "- sufficient:信息是否足以撰写报告\n"
            "- gaps:仍缺失的关键信息(简要)\n"
            f"- new_queries:sufficient=false 时给出不超过 {settings.max_new_queries} 条新的检索查询",
        )
    except Exception as e:
        logger.warning("reflect 降级(直接收敛): %s", e)
        current["gaps"] = "反思环节异常,提前收敛"
        _emit({"type": "reflect", "sufficient": True, "gaps": current["gaps"]})
        return {
            "rounds": [current],
            "iteration": current["round"],
            "sufficient": True,
            "pending_queries": [],
            "degraded": True,
        }
    new_queries = [
        q.strip() for q in out.new_queries if q.strip() and q.strip() not in searched
    ][: settings.max_new_queries]
    current["gaps"] = out.gaps
    _emit({"type": "reflect", "sufficient": out.sufficient, "gaps": out.gaps})
    return {
        "rounds": [current],  # 本轮完整记录落档
        "iteration": current["round"],
        "sufficient": out.sufficient,
        "pending_queries": new_queries,
    }


# ---------- synthesize ----------

async def synthesize_node(state: ResearchState) -> dict:
    """基于 findings 综合报告正文并落盘(头部/来源/置信度由 report.py 程序渲染)。"""
    from app.report import render_report, save_outputs

    _emit({"type": "synthesize_start"})
    findings_lines = []
    url_index: dict[str, int] = {}
    for f in state["findings"]:
        url_index.setdefault(f["url"], len(url_index) + 1)
    for f in state["findings"]:
        findings_lines.append(f"[{url_index[f['url']]}] {f['point']}(佐证:{f['quote']})")
    plan_lines = "\n".join(f"- {q}" for q in state["plan"])
    gaps = "; ".join(r.get("gaps", "") for r in state["rounds"] if r.get("gaps"))

    prompt = (
        "你是研究报告撰写者。基于研究发现撰写研究报告的正文部分(markdown)。\n\n"
        f"研究主题:{state['topic']}\n\n参考子问题(目录可按内容自由重组,不必逐一对应):\n{plan_lines}\n\n"
        f"研究发现(格式:[来源编号] 要点(佐证:原文摘录)):\n"
        + "\n".join(findings_lines)
        + "\n\n撰写要求:\n"
        "1. 依次输出以下章节(用 ## 二级标题):## 摘要、## 分节正文(若干节,标题自拟)、"
        "## 关键结论、## 遗留问题\n"
        "2. 结论只有能对应上述研究发现(有佐证摘录)才标注 [n] 角标,n 为来源编号;\n"
        "3. 无法对应任何来源的论断,句末标注「(模型推断)」,不得使用角标;\n"
        "4. 报告语言跟随主题语言;引用的原文保持原语言;\n"
        "5. 不要输出报告标题、来源列表与置信度说明(系统自动生成)。\n"
    )
    if gaps:
        prompt += f"\n研究遗留缺口(供「遗留问题」参考):{gaps}\n"

    degraded = bool(state.get("degraded"))
    try:
        resp = await get_llm(temperature=0.3).ainvoke([HumanMessage(content=prompt)])
        body_md = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception as e:
        # 降级:程序拼装最简报告
        logger.warning("synthesize 降级(程序拼装): %s", e)
        body_md = (
            "## 摘要\n\n(报告生成异常,以下为要点罗列)\n\n"
            "## 分节正文\n\n"
            + "\n".join(f"- {f['point']}" for f in state["findings"])
            + "\n\n## 关键结论\n\n(生成异常,略)\n\n## 遗留问题\n\n- 报告生成环节异常,建议重跑\n"
        )
        degraded = True

    # 统计角标引用次数(只统计 LLM 正文,来源列表自身的 [n] 不计),回写 cited
    cited = Counter(re.findall(r"\[(\d+)\]", body_md))
    index_url = {n: u for u, n in url_index.items()}
    sources_final = dict(state["sources"])
    for n_str, cnt in cited.items():
        u = index_url.get(int(n_str))
        if u in sources_final:
            meta = dict(sources_final[u])
            meta["cited"] = cnt
            sources_final[u] = meta

    state_for_render = {**state, "degraded": degraded, "sources": sources_final}
    report_md = render_report(state_for_render, body_md)
    save_outputs(state_for_render, report_md, status="incomplete" if degraded else "completed")
    _emit({"type": "report_done", "task_id": state.get("task_id", "")})
    return {"report_md": report_md, "sources": sources_final, "degraded": degraded}
