"""图冒烟测试:mock 搜索 + mock LLM,验证全路径 / 5 轮硬上限 / 搜索预算耗尽。"""
import json

import pytest

from app import report as report_mod
from app.config import settings
from app.graph import nodes as graph_nodes
from app.graph.builder import build_graph
from app.graph.state import initial_state
from app.schemas import (
    Finding,
    FindingsOutput,
    PlanOutput,
    ReflectOutput,
    SelectOutput,
)
from langgraph.checkpoint.memory import InMemorySaver

_SEARCH_RESULTS = [
    {
        "url": f"https://example.com/{i}",
        "title": f"文章{i}",
        "summary": f"关于主题的摘要{i}",
        "date_published": "2026-08-0" + str(i + 1),
    }
    for i in range(4)
]


class _Msg:
    def __init__(self, content):
        self.content = content


async def _fake_web_search(query, retry=1):
    return [dict(r) for r in _SEARCH_RESULTS]


async def _fake_fetch_page(url):
    return f"这是 {url} 的正文内容。关键事实:方案 A 于 2026 年发布,原文写着重要结论。"


def _make_fixtures(monkeypatch, tmp_path, sufficient=True, new_queries=None):
    """打桩 LLM/搜索/抓取,报告落盘重定向到 tmp_path。"""
    state = {"calls": 0}

    async def fake_structured(schema, prompt, retry=1):
        if schema is PlanOutput:
            return PlanOutput(sub_questions=["子问题一", "子问题二", "子问题三"])
        if schema is SelectOutput:
            return SelectOutput(urls=[r["url"] for r in _SEARCH_RESULTS[:2]])
        if schema is FindingsOutput:
            return FindingsOutput(
                findings=[
                    Finding(
                        point="方案 A 于 2026 年发布",
                        quote="方案 A 于 2026 年发布",
                        url="https://example.com/0",
                    )
                ]
            )
        if schema is ReflectOutput:
            state["calls"] += 1
            qs = new_queries() if callable(new_queries) else (new_queries or [])
            return ReflectOutput(
                sufficient=sufficient,
                gaps="还缺少方案 B 的信息",
                new_queries=qs,
            )
        raise AssertionError(f"未预期的 schema: {schema}")

    async def fake_llm_invoke(messages):
        return _Msg(
            "## 摘要\n\n测试摘要。\n\n## 分节正文\n\n- 方案 A 已发布 [1]。\n"
            "\n## 关键结论\n\n- 方案 A [1]\n\n## 遗留问题\n\n- 缺方案 B"
        )

    class _FakeLLM:
        def __init__(self, temperature=0.2):
            pass

        async def ainvoke(self, messages):
            return await fake_llm_invoke(messages)

    monkeypatch.setattr(graph_nodes, "web_search", _fake_web_search)
    monkeypatch.setattr(graph_nodes, "fetch_page", _fake_fetch_page)
    monkeypatch.setattr(graph_nodes, "_structured", fake_structured)
    monkeypatch.setattr(graph_nodes, "get_llm", lambda temperature=0.2: _FakeLLM())
    monkeypatch.setattr(report_mod, "REPORTS_DIR", tmp_path / "reports")
    return state


async def _run(task_id="t-smoke"):
    graph = build_graph(checkpointer=InMemorySaver())
    return await graph.ainvoke(
        initial_state(task_id, "测试主题"),
        config={"configurable": {"thread_id": task_id}},
    )


async def test_full_path_single_round(monkeypatch, tmp_path):
    """reflect 判定充分 → 1 轮收敛,报告与过程记录落盘。"""
    _make_fixtures(monkeypatch, tmp_path, sufficient=True)
    final = await _run("t-full")
    assert len(final["rounds"]) == 1
    assert final["sufficient"] is True
    assert final["search_count"] == 3  # 3 个子问题各检索 1 次
    assert final["findings"], "应有要点写入"
    assert "[1]" in final["report_md"]

    d = tmp_path / "reports" / "t-full"
    assert (d / "report.md").exists()
    process = json.loads((d / "process.json").read_text())
    assert process["status"] == "completed"
    assert process["stats"]["rounds"] == 1
    assert process["stats"]["searches"] == 3
    assert process["plan"] == ["子问题一", "子问题二", "子问题三"]
    md = (d / "report.md").read_text()
    assert "信息最新截至 2026-08-02" in md  # 已读来源(前 2 条)最新日期
    assert "## 来源列表" in md and "## 置信度说明" in md
    # cited 回写:来源 [1] 被引用 2 次
    assert process["sources"]["https://example.com/0"]["cited"] == 2


async def test_hard_round_limit(monkeypatch, tmp_path):
    """持续 insufficient → 达到 5 轮硬上限强制收敛。"""
    counter = {"n": 0}

    def fresh_queries():
        counter["n"] += 1
        return [f"补充查询{counter['n']}"]

    _make_fixtures(monkeypatch, tmp_path, sufficient=False, new_queries=fresh_queries)
    final = await _run("t-limit")
    assert len(final["rounds"]) == settings.max_rounds == 5
    assert final["sufficient"] is False  # 由硬上限收敛,而非充分判定
    assert (tmp_path / "reports" / "t-limit" / "report.md").exists()


async def test_search_budget_exhausted(monkeypatch, tmp_path):
    """累计搜索次数达到预算 → 强制收敛。"""
    monkeypatch.setattr(settings, "search_budget", 2, raising=False)
    counter = {"n": 0}

    def fresh_queries():
        counter["n"] += 1
        return [f"补充查询{counter['n']}"]

    _make_fixtures(monkeypatch, tmp_path, sufficient=False, new_queries=fresh_queries)
    final = await _run("t-budget")
    assert final["search_count"] <= 2
    assert len(final["rounds"]) == 1  # 首轮即耗尽预算,直接收敛
    assert (tmp_path / "reports" / "t-budget" / "report.md").exists()


async def test_fetch_failure_falls_back_to_summary(monkeypatch, tmp_path):
    """抓取失败 → 搜索摘要兜底,要点标记 from_summary。"""
    async def failing_fetch(url):
        return None

    _make_fixtures(monkeypatch, tmp_path, sufficient=True)
    monkeypatch.setattr(graph_nodes, "fetch_page", failing_fetch)
    final = await _run("t-fallback")
    assert any(f["from_summary"] for f in final["findings"])
    assert final["sources"]["https://example.com/0"]["from_summary"] is True
    md = final["report_md"]
    assert "(基于摘要)" in md


async def test_degraded_on_plan_failure(monkeypatch, tmp_path):
    """plan 节点异常 → 降级不中断,报告标注不完整。"""
    async def exploding_structured(schema, prompt, retry=1):
        raise RuntimeError("LLM 挂了")

    _make_fixtures(monkeypatch, tmp_path, sufficient=True)
    monkeypatch.setattr(graph_nodes, "_structured", exploding_structured)
    final = await _run("t-degraded")
    assert final["degraded"] is True
    assert final["plan"] == ["测试主题"]  # 降级为主题本身
    md = final["report_md"]
    assert "不完整报告" in md
    process = json.loads(
        (tmp_path / "reports" / "t-degraded" / "process.json").read_text()
    )
    assert process["status"] == "incomplete"
