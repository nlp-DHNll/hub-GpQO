"""工作流测试：用假 chain 替换 LLM 调用，验证图的重试、预算与降级路径。

与 openai-agents 版 test_workflow.py 的对应：mock `Runner.run` 改为
mock 各 agent 的 `chain.ainvoke`。
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import sql_agent.graph as graph_module
from sql_agent.config import settings
from sql_agent.db.catalog import SchemaCatalog
from sql_agent.db.executor import SQLExecutor
from sql_agent.db.validator import SQLValidator
from sql_agent.graph import SQLAgentGraph
from sql_agent.models import FinalAnswer, SQLDraft, TableSelection


@pytest.fixture(scope="module")
def graph() -> SQLAgentGraph:
    catalog = SchemaCatalog(Path("ref/chinook.db"))
    return SQLAgentGraph(
        catalog=catalog,
        validator=SQLValidator(catalog.db_path),
        executor=SQLExecutor(catalog.db_path),
    )


def _patch_chains(monkeypatch, outputs):
    """按调用顺序依次返回 outputs，并记录 (chain 名, prompt)。"""

    calls = []
    remaining = iter(outputs)

    def make_chain(name: str):
        async def ainvoke(prompt, config=None, **kwargs):
            calls.append((name, prompt))
            return next(remaining)

        return SimpleNamespace(ainvoke=ainvoke)

    monkeypatch.setattr(
        graph_module, "table_selector_chain", make_chain("TableSelectAgent")
    )
    monkeypatch.setattr(
        graph_module, "sql_generator_chain", make_chain("SQLGeneratorAgent")
    )
    monkeypatch.setattr(
        graph_module, "sql_rewriter_chain", make_chain("SQLRewriteAgent")
    )
    monkeypatch.setattr(
        graph_module, "result_summary_chain", make_chain("ResultSummaryAgent")
    )
    return calls


def test_happy_path(graph: SQLAgentGraph, monkeypatch) -> None:
    outputs = [
        TableSelection(tables=["albums"], reason="统计专辑数量", confidence=0.9),
        SQLDraft(sql="SELECT COUNT(*) AS n FROM albums", explanation="count"),
        FinalAnswer(answer="共 347 张专辑。", evidence=["347"]),
    ]
    calls = _patch_chains(monkeypatch, outputs)

    result = asyncio.run(graph.run("总共有多少张专辑？"))

    assert result.error is None
    assert result.tables == ["albums"]
    assert result.row_count == 1
    assert result.answer == "共 347 张专辑。"
    assert len(calls) == 3
    assert [name for name, _ in calls] == [
        "TableSelectAgent",
        "SQLGeneratorAgent",
        "ResultSummaryAgent",
    ]


def test_rewrite_path(graph: SQLAgentGraph, monkeypatch) -> None:
    outputs = [
        TableSelection(tables=["albums"], reason="统计专辑数量", confidence=0.9),
        SQLDraft(sql="SELECT COUNT(ArtistId FROM albums", explanation="bad"),
        SQLDraft(sql="SELECT COUNT(ArtistId) AS n FROM albums", explanation="fixed"),
        FinalAnswer(answer="共有 275 位艺人。", evidence=["275"]),
    ]
    calls = _patch_chains(monkeypatch, outputs)

    result = asyncio.run(graph.run("专辑里有多少位不同的艺人？"))

    assert result.repair_attempts == 1
    assert result.error is None
    assert "COUNT(ArtistId)" in (result.sql or "")
    assert [name for name, _ in calls] == [
        "TableSelectAgent",
        "SQLGeneratorAgent",
        "SQLRewriteAgent",
        "ResultSummaryAgent",
    ]


def test_empty_result_skips_summary_agent(graph: SQLAgentGraph, monkeypatch) -> None:
    outputs = [
        TableSelection(tables=["albums"], reason="查不存在的专辑", confidence=0.9),
        SQLDraft(sql="SELECT * FROM albums WHERE AlbumId = -1", explanation="empty"),
    ]
    calls = _patch_chains(monkeypatch, outputs)

    result = asyncio.run(graph.run("编号为 -1 的专辑是什么？"))

    assert result.row_count == 0
    assert result.answer == "未查询到符合条件的数据。"
    assert len(calls) == 2


def test_unknown_table_is_rejected(graph: SQLAgentGraph, monkeypatch) -> None:
    outputs = [
        TableSelection(tables=["not_a_table"], reason="bad", confidence=0.1),
        TableSelection(tables=["albums"], reason="fixed", confidence=0.9),
        SQLDraft(sql="SELECT COUNT(*) AS n FROM albums", explanation="count"),
        FinalAnswer(answer="共 347 张专辑。", evidence=["347"]),
    ]
    calls = _patch_chains(monkeypatch, outputs)

    result = asyncio.run(graph.run("总共有多少张专辑？"))

    assert result.error is None
    assert result.tables == ["albums"]
    assert [name for name, _ in calls].count("TableSelectAgent") == 2


def test_clarification_stops_before_generation(graph: SQLAgentGraph, monkeypatch) -> None:
    outputs = [
        TableSelection(
            tables=[],
            reason="与数据库无关",
            confidence=0.1,
            needs_clarification=True,
            clarification_question="这个问题与音乐库无关，请提供数据库相关问题。",
        ),
    ]
    calls = _patch_chains(monkeypatch, outputs)

    result = asyncio.run(graph.run("今天天气怎么样？"))

    assert result.answer == "这个问题与音乐库无关，请提供数据库相关问题。"
    assert result.sql is None
    assert len(calls) == 1


def test_max_repair_attempts_returns_error(monkeypatch) -> None:
    catalog = SchemaCatalog(Path("ref/chinook.db"))
    graph = SQLAgentGraph(
        catalog=catalog,
        validator=SQLValidator(catalog.db_path),
        executor=SQLExecutor(catalog.db_path),
        max_repair_attempts=0,
    )
    outputs = [
        TableSelection(tables=["albums"], reason="bad sql", confidence=0.9),
        SQLDraft(sql="SELECT nope FROM albums", explanation="bad"),
    ]
    _patch_chains(monkeypatch, outputs)

    result = asyncio.run(graph.run("测试失败路径"))

    assert result.error is not None
    assert result.repair_attempts == 0
    assert "最大修复次数" in result.answer


def test_summary_failure_falls_back_to_table(graph: SQLAgentGraph, monkeypatch) -> None:
    outputs = [
        TableSelection(tables=["albums"], reason="前 3 张专辑", confidence=0.9),
        SQLDraft(sql="SELECT Title FROM albums ORDER BY AlbumId LIMIT 3", explanation="top3"),
        # ResultSummaryAgent 返回了错误类型 → isinstance 检查失败 → 触发降级输出
        SQLDraft(sql="SELECT 1", explanation="wrong type"),
    ]
    _patch_chains(monkeypatch, outputs)

    result = asyncio.run(graph.run("前 3 张专辑是什么？"))

    assert result.error is None
    assert result.row_count == 3
    assert "查询返回 3 行" in result.answer
    assert result.caveats and "降级" in result.caveats[0]


def test_settings_db_path_exists() -> None:
    assert settings.db_path.exists()
