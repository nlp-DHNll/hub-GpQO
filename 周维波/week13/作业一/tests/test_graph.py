"""图编排测试：用 Fake 链驱动完整状态机，DB 校验/执行走真实只读实现。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from sql_agent.db.catalog import SchemaCatalog
from sql_agent.db.executor import SQLExecutor
from sql_agent.db.validator import SQLValidator
from sql_agent.graph import NODE_LABELS
from sql_agent.graph.builder import build_sql_agent_graph
from sql_agent.graph.runner import SQLAgentGraph
from sql_agent.models import FinalAnswer, SQLDraft, TableSelection

DB_PATH = Path(__file__).resolve().parents[1] / "ref" / "chinook.db"


class FakeChain:
    """按队列顺序返回结构化结果；用尽后重复最后一个。"""

    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = list(outputs)
        self.calls = 0
        self.inputs: list[str] = []

    async def ainvoke(self, payload: dict) -> Any:
        self.inputs.append(payload.get("input", ""))
        index = min(self.calls, len(self.outputs) - 1)
        self.calls += 1
        result = self.outputs[index]
        if isinstance(result, Exception):
            raise result
        return result


def _selector(*tables: str, **kwargs) -> FakeChain:
    return FakeChain(
        [
            TableSelection(
                tables=list(tables),
                reason="测试用选表结果",
                confidence=0.9,
                **kwargs,
            )
        ]
    )


def _install_chains(
    monkeypatch: pytest.MonkeyPatch,
    *,
    selector: FakeChain,
    generator: FakeChain,
    rewriter: FakeChain | None = None,
    summarizer: FakeChain | None = None,
) -> None:
    import sql_agent.graph.nodes as nodes_module

    monkeypatch.setattr(nodes_module, "get_table_selector_chain", lambda: selector)
    monkeypatch.setattr(nodes_module, "get_sql_generator_chain", lambda: generator)
    monkeypatch.setattr(
        nodes_module,
        "get_sql_rewriter_chain",
        lambda: rewriter or FakeChain([SQLDraft(sql="SELECT 1")]),
    )
    monkeypatch.setattr(
        nodes_module,
        "get_result_summary_chain",
        lambda: summarizer or FakeChain([FinalAnswer(answer="已汇总。")]),
    )


def _make_agent(monkeypatch: pytest.MonkeyPatch, max_repair: int = 3, **chains) -> SQLAgentGraph:
    _install_chains(monkeypatch, **chains)
    catalog = _shared_catalog()
    compiled = build_sql_agent_graph(
        catalog=catalog,
        validator=SQLValidator(DB_PATH),
        executor=SQLExecutor(DB_PATH),
    )
    return SQLAgentGraph(compiled, max_repair_attempts=max_repair)


_CATALOG: SchemaCatalog | None = None


def _shared_catalog() -> SchemaCatalog:
    """profiling 一次即可，测试间复用只读 catalog，避免每条用例重复采样。"""

    global _CATALOG
    if _CATALOG is None:
        _CATALOG = SchemaCatalog(DB_PATH)
    return _CATALOG


def test_happy_path_returns_answer_and_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _make_agent(
        monkeypatch,
        selector=_selector("albums"),
        generator=FakeChain([SQLDraft(sql="SELECT COUNT(*) AS total FROM albums")]),
        summarizer=FakeChain(
            [FinalAnswer(answer="数据库中共有 347 张专辑。", evidence=["347"])]
        ),
    )

    result = asyncio.run(agent.run_full("总共有多少张专辑？"))
    output = result["output"]

    assert output.answer == "数据库中共有 347 张专辑。"
    assert output.error is None
    assert output.tables == ["albums"]
    assert output.row_count == 1
    assert output.repair_attempts == 0
    assert output.evidence == ["347"]
    assert output.sql == "SELECT COUNT(*) AS total FROM albums"
    assert result["columns"] == ["total"]
    assert result["rows"] == [["347"]]

    nodes = [stage["node"] for stage in result["stages"]]
    assert nodes == [
        "select_tables",
        "build_schema",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "summarize",
        "finalize",
    ]
    assert set(nodes) <= set(NODE_LABELS)


def test_empty_result_skips_summary_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    summarizer = FakeChain([FinalAnswer(answer="不应被调用")])
    agent = _make_agent(
        monkeypatch,
        selector=_selector("albums"),
        generator=FakeChain([SQLDraft(sql="SELECT Title FROM albums WHERE AlbumId = -1")]),
        summarizer=summarizer,
    )

    output = asyncio.run(agent.run("没有这张专辑的专辑名"))

    assert summarizer.calls == 0
    assert output.row_count == 0
    assert output.answer == "未查询到符合条件的数据。"
    assert output.error is None
    assert output.repair_attempts == 0


def test_validation_failure_is_rewritten_once(monkeypatch: pytest.MonkeyPatch) -> None:
    rewriter = FakeChain([SQLDraft(sql="SELECT COUNT(*) AS total FROM albums")])
    summarizer = FakeChain([FinalAnswer(answer="共有 347 张专辑。")])
    agent = _make_agent(
        monkeypatch,
        selector=_selector("albums"),
        generator=FakeChain([SQLDraft(sql="SELECT Name FROM albums WHERE NotAColumn = 1")]),
        rewriter=rewriter,
        summarizer=summarizer,
    )

    output = asyncio.run(agent.run("专辑数量"))

    assert rewriter.calls == 1
    assert output.repair_attempts == 1
    assert output.error is None
    assert output.sql == "SELECT COUNT(*) AS total FROM albums"
    assert output.answer == "共有 347 张专辑。"


def test_repair_budget_exhausted_terminates(monkeypatch: pytest.MonkeyPatch) -> None:
    rewriter = FakeChain([SQLDraft(sql="SELECT MissingCol FROM albums")])
    agent = _make_agent(
        monkeypatch,
        max_repair=2,
        selector=_selector("albums"),
        generator=FakeChain([SQLDraft(sql="SELECT NopeColumn FROM albums")]),
        rewriter=rewriter,
    )

    result = asyncio.run(agent.run_full("随便问点什么"))
    output = result["output"]

    assert rewriter.calls == 2
    assert output.repair_attempts == 2
    assert output.error is not None
    assert output.answer == "无法生成可执行的 SQL，已达到最大修复次数。"
    assert output.row_count == 0
    assert "mark_exhausted" in [stage["node"] for stage in result["stages"]]


def test_cannot_fix_terminates_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    rewriter = FakeChain(
        [SQLDraft(sql="", explanation="该问题需要数据库之外的数据", cannot_fix=True)]
    )
    agent = _make_agent(
        monkeypatch,
        selector=_selector("albums"),
        generator=FakeChain([SQLDraft(sql="SELECT NopeColumn FROM albums")]),
        rewriter=rewriter,
    )

    output = asyncio.run(agent.run("天气怎么样"))

    assert rewriter.calls == 1
    assert output.repair_attempts == 0
    assert output.answer.startswith("当前数据库无法回答该问题：")
    assert output.error is not None


def test_clarification_short_circuits_to_finalize(monkeypatch: pytest.MonkeyPatch) -> None:
    generator = FakeChain([SQLDraft(sql="SELECT 1")])
    agent = _make_agent(
        monkeypatch,
        selector=FakeChain(
            [
                TableSelection(
                    tables=[],
                    reason="问题与数据库无关",
                    confidence=0.2,
                    needs_clarification=True,
                    clarification_question="您想查询哪类数据？",
                )
            ]
        ),
        generator=generator,
    )

    output = asyncio.run(agent.run("帮我订一张机票"))

    assert generator.calls == 0
    assert output.answer == "您想查询哪类数据？"
    assert output.sql is None
    assert output.row_count == 0
    assert output.error is None


def test_unknown_table_triggers_one_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    selector = FakeChain(
        [
            TableSelection(tables=["albumz"], reason="猜错表名", confidence=0.4),
            TableSelection(tables=["albums"], reason="修正为 albums", confidence=0.95),
        ]
    )
    agent = _make_agent(
        monkeypatch,
        selector=selector,
        generator=FakeChain([SQLDraft(sql="SELECT COUNT(*) AS total FROM albums")]),
        summarizer=FakeChain([FinalAnswer(answer="共有 347 张专辑。")]),
    )

    output = asyncio.run(agent.run("专辑数"))

    assert selector.calls == 2
    assert "albumz" in selector.inputs[1]  # 第二次带上了修正反馈
    assert output.tables == ["albums"]
    assert output.error is None


def test_disconnected_tables_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    selector = FakeChain(
        [
            TableSelection(tables=["albums", "customers"], reason="跨表但无外键", confidence=0.5),
            TableSelection(tables=["albums", "tracks"], reason="改选可连接的表", confidence=0.9),
        ]
    )
    agent = _make_agent(
        monkeypatch,
        selector=selector,
        generator=FakeChain([SQLDraft(sql="SELECT COUNT(*) AS total FROM albums")]),
        summarizer=FakeChain([FinalAnswer(answer="ok")]),
    )

    output = asyncio.run(agent.run("专辑与曲目"))

    assert selector.calls == 2
    assert "外键连接" in selector.inputs[1]
    assert output.tables == ["albums", "tracks"]


def test_stream_emits_stage_events_and_final(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _make_agent(
        monkeypatch,
        selector=_selector("albums"),
        generator=FakeChain([SQLDraft(sql="SELECT COUNT(*) AS total FROM albums")]),
        summarizer=FakeChain([FinalAnswer(answer="共有 347 张专辑。")]),
    )

    async def collect() -> list[dict]:
        return [event async for event in agent.stream("总共有多少张专辑？")]

    events = asyncio.run(collect())
    starts = [e for e in events if e["type"] == "stage_start"]
    ends = [e for e in events if e["type"] == "stage_end"]
    final = events[-1]

    assert [e["node"] for e in starts] == [
        "select_tables",
        "build_schema",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "summarize",
        "finalize",
    ]
    assert [e["node"] for e in ends] == [e["node"] for e in starts]
    assert all(e["label"] for e in starts)
    assert final["type"] == "final"
    assert final["output"]["answer"] == "共有 347 张专辑。"
    assert final["columns"] == ["total"]
    assert final["rows"] == [["347"]]
    assert len(final["stages"]) == 7


def test_empty_question_is_rejected_without_calling_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summarizer = FakeChain([FinalAnswer(answer="不应被调用")])
    agent = _make_agent(
        monkeypatch,
        selector=_selector("albums"),
        generator=FakeChain([SQLDraft(sql="SELECT 1")]),
        summarizer=summarizer,
    )

    output = asyncio.run(agent.run("   "))

    assert output.answer == "请输入要查询的问题。"
    assert summarizer.calls == 0
