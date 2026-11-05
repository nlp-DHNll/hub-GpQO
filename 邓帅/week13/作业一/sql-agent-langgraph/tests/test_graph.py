"""工作流测试：用假 chain 替换 LLM 调用，验证图的重试、预算与降级路径。

与 week12 版的差异：修复循环移入子图，另新增三个 LangGraph 特性用例：
- 多轮历史注入（InMemorySaver + 同 thread_id）；
- 澄清 → 补充回答的真多轮闭环；
- SqliteSaver 落盘后跨实例（模拟进程重启）恢复会话。
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

import sql_agent.graph as graph_module
from sql_agent.config import settings
from sql_agent.db.catalog import SchemaCatalog
from sql_agent.db.executor import SQLExecutor
from sql_agent.db.validator import SQLValidator
from sql_agent.graph import SQLAgentGraph
from sql_agent.models import FinalAnswer, SQLDraft, TableSelection


def _components() -> dict:
    catalog = SchemaCatalog(Path("ref/chinook.db"))
    return {
        "catalog": catalog,
        "validator": SQLValidator(catalog.db_path),
        "executor": SQLExecutor(catalog.db_path),
    }


@pytest.fixture(scope="module")
def graph() -> SQLAgentGraph:
    return SQLAgentGraph(**_components())


@pytest.fixture(scope="module")
def memory_graph() -> SQLAgentGraph:
    """带 InMemorySaver 的图，供多轮用例使用。"""

    return SQLAgentGraph(**_components(), checkpointer=InMemorySaver())


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
    assert [name for name, _ in calls] == [
        "TableSelectAgent",
        "SQLGeneratorAgent",
        "ResultSummaryAgent",
    ]


def test_rewrite_path_in_subgraph(graph: SQLAgentGraph, monkeypatch) -> None:
    """坏 SQL 在修复子图内被改写修复，主图无感知循环细节。"""

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


def test_clarification_stops_before_generation(
    graph: SQLAgentGraph, monkeypatch
) -> None:
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


def test_multi_turn_history_injected(memory_graph: SQLAgentGraph, monkeypatch) -> None:
    """第二轮同 thread 提问，上一轮问答应注入 table_select 与 generate 的 prompt。"""

    outputs = [
        TableSelection(tables=["albums"], reason="统计专辑", confidence=0.9),
        SQLDraft(sql="SELECT COUNT(*) AS n FROM albums", explanation="count"),
        FinalAnswer(answer="共 347 张专辑。", evidence=["347"]),
    ]
    _patch_chains(monkeypatch, outputs)
    first = asyncio.run(memory_graph.run("总共有多少张专辑？", thread_id="turn-case"))
    assert first.error is None

    outputs2 = [
        TableSelection(tables=["albums"], reason="追问均价", confidence=0.9),
        SQLDraft(
            sql="SELECT AVG(UnitPrice) AS p FROM albums, tracks LIMIT 1",
            explanation="avg",
        ),
        FinalAnswer(answer="均价见 SQL。", evidence=[]),
    ]
    calls2 = _patch_chains(monkeypatch, outputs2)
    second = asyncio.run(memory_graph.run("那均价是多少？", thread_id="turn-case"))
    assert second.error is None

    select_prompt = calls2[0][1]["prompt"]
    generate_prompt = calls2[1][1]["prompt"]
    assert "总共有多少张专辑" in select_prompt  # 上一轮问题
    assert "共 347 张专辑" in select_prompt  # 上一轮答案
    assert "总共有多少张专辑" in generate_prompt


def test_clarification_then_followup(memory_graph: SQLAgentGraph, monkeypatch) -> None:
    """澄清不是死路：同 thread 补充回答后，图带着澄清上下文继续走完全链路。"""

    outputs = [
        TableSelection(
            tables=[],
            reason="歧义",
            confidence=0.2,
            needs_clarification=True,
            clarification_question="你想统计哪个国家的客户？",
        ),
    ]
    _patch_chains(monkeypatch, outputs)
    first = asyncio.run(memory_graph.run("统计客户数量", thread_id="clar-case"))
    assert "哪个国家" in first.answer

    outputs2 = [
        TableSelection(tables=["customers"], reason="按国家统计", confidence=0.9),
        SQLDraft(
            sql="SELECT COUNT(*) AS n FROM customers WHERE Country = 'USA'",
            explanation="count usa",
        ),
        FinalAnswer(answer="美国客户 13 位。", evidence=["13"]),
    ]
    calls2 = _patch_chains(monkeypatch, outputs2)
    second = asyncio.run(memory_graph.run("美国的", thread_id="clar-case"))
    assert second.error is None
    assert second.answer == "美国客户 13 位。"

    # 澄清问答作为历史进入第二轮的选表 prompt。
    select_prompt = calls2[0][1]["prompt"]
    assert "统计客户数量" in select_prompt
    assert "哪个国家" in select_prompt


def test_max_repair_attempts_returns_error(monkeypatch) -> None:
    graph = SQLAgentGraph(**_components(), max_repair_attempts=0)
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


def test_sqlite_saver_persistence_across_instances(tmp_path, monkeypatch) -> None:
    """SqliteSaver 落盘：新实例（模拟进程重启）能读到旧 thread 的会话。"""

    db_file = tmp_path / "checkpoints.sqlite"

    async def scenario() -> None:
        outputs = [
            TableSelection(tables=["albums"], reason="统计专辑", confidence=0.9),
            SQLDraft(sql="SELECT COUNT(*) AS n FROM albums", explanation="count"),
            FinalAnswer(answer="共 347 张专辑。", evidence=["347"]),
        ]
        _patch_chains(monkeypatch, outputs)
        async with AsyncSqliteSaver.from_conn_string(str(db_file)) as saver:
            graph = SQLAgentGraph(**_components(), checkpointer=saver)
            first = await graph.run("总共有多少张专辑？", thread_id="persist-t1")
        assert first.error is None

        # 全新 graph + 全新 saver，同一个磁盘文件 → 模拟进程重启后恢复会话。
        async with AsyncSqliteSaver.from_conn_string(str(db_file)) as saver:
            restarted = SQLAgentGraph(**_components(), checkpointer=saver)
            snapshot = await restarted.app.aget_state(
                restarted.make_config("persist-t1")
            )
            assert snapshot.values.get("final") is not None

            turn_input, _ = await restarted.prepare_turn("换个问题", "persist-t1")
            assert len(turn_input["history"]) == 1
            assert turn_input["history"][0].question == "总共有多少张专辑？"
            # 一轮残留字段必须被重置，否则路由会误判上一轮已终止。
            assert turn_input["final"] is None
            assert turn_input["attempts"] == []

    asyncio.run(scenario())


def test_settings_db_path_exists() -> None:
    assert settings.db_path.exists()
