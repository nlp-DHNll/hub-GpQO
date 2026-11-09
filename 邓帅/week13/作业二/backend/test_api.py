"""API 测试：TestClient + mock LLM chain，验证 SSE 事件协议与多轮 thread 透传。

LLM 调用全部 mock（与作业一 test_graph 同手法），无需 API key。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

# 作业一的 src 注入（与 main.py 一致），让 sql_agent 可导入。
WEEK13_ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT1_SRC = WEEK13_ROOT / "作业一" / "sql-agent-langgraph" / "src"
if str(ASSIGNMENT1_SRC) not in sys.path:
    sys.path.insert(0, str(ASSIGNMENT1_SRC))

import pytest
import sql_agent.graph as graph_module
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sql_agent.db.catalog import SchemaCatalog
from sql_agent.db.executor import SQLExecutor
from sql_agent.db.validator import SQLValidator
from sql_agent.graph import SQLAgentGraph
from sql_agent.models import FinalAnswer, SQLDraft, TableSelection

from main import create_app

CHINOOK = ASSIGNMENT1_SRC.parent / "ref" / "chinook.db"


def _build_graph() -> SQLAgentGraph:
    catalog = SchemaCatalog(CHINOOK)
    return SQLAgentGraph(
        catalog=catalog,
        validator=SQLValidator(catalog.db_path),
        executor=SQLExecutor(catalog.db_path),
        checkpointer=InMemorySaver(),
    )


def _patch_chains(monkeypatch, outputs):
    calls = []
    remaining = iter(outputs)

    def make_chain(name: str):
        async def ainvoke(prompt, config=None, **kwargs):
            calls.append((name, prompt))
            return next(remaining)

        return SimpleNamespace(ainvoke=ainvoke)

    for module_attr, chain_name in [
        ("table_selector_chain", "TableSelectAgent"),
        ("sql_generator_chain", "SQLGeneratorAgent"),
        ("sql_rewriter_chain", "SQLRewriteAgent"),
        ("result_summary_chain", "ResultSummaryAgent"),
    ]:
        monkeypatch.setattr(graph_module, module_attr, make_chain(chain_name))
    return calls


def _parse_sse(text: str) -> list[tuple[str, str]]:
    """把 SSE 文本解析成 (event, data) 列表；兼容 \n 与 \r\n 行尾。"""

    events: list[tuple[str, str]] = []
    event, data = "", ""
    for line in text.splitlines():
        line = line.rstrip("\r")
        if not line:
            if event:
                events.append((event, data))
            event, data = "", ""
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data = line[len("data:") :].strip()
    if event:
        events.append((event, data))
    return events


def _post(client: TestClient, question: str, thread_id: str | None = None):
    return client.post(
        "/api/chat", json={"question": question, "thread_id": thread_id}
    )


def test_sse_event_sequence_happy_path(monkeypatch) -> None:
    outputs = [
        TableSelection(tables=["albums"], reason="统计专辑", confidence=0.9),
        SQLDraft(sql="SELECT COUNT(*) AS n FROM albums", explanation="count"),
        FinalAnswer(answer="共 347 张专辑。", evidence=["347"]),
    ]
    _patch_chains(monkeypatch, outputs)

    with TestClient(create_app(graph=_build_graph())) as client:
        resp = _post(client, "总共有多少张专辑？")

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    names = [name for name, _ in events]

    assert names[0] == "meta"
    assert names[-1] == "done"
    assert "result" in names
    # 主图四节点的进度事件按序出现
    progress = [json.loads(d) for n, d in events if n == "progress"]
    stages = [p["stage"] for p in progress]
    assert "table_selected" in stages
    assert "generated" in stages
    assert "executed" in stages
    assert "done" in stages
    # executed 之后有 sql 事件
    assert "sql" in names
    result = next(json.loads(d) for n, d in events if n == "result")
    assert result["answer"] == "共 347 张专辑。"
    assert result["sql"].startswith("SELECT COUNT")


def test_clarification_event(monkeypatch) -> None:
    outputs = [
        TableSelection(
            tables=[],
            reason="无关",
            confidence=0.1,
            needs_clarification=True,
            clarification_question="请提供与音乐库相关的问题。",
        ),
    ]
    _patch_chains(monkeypatch, outputs)

    with TestClient(create_app(graph=_build_graph())) as client:
        resp = _post(client, "今天天气怎么样？")

    events = _parse_sse(resp.text)
    names = [name for name, _ in events]
    assert "clarification" in names
    clarification = next(
        json.loads(d) for n, d in events if n == "clarification"
    )
    assert "音乐库" in clarification["question"]
    # 澄清轮没有 sql/result 事件
    assert "sql" not in names
    assert "result" in names  # final 本身也会作为 result 事件发出


def test_multi_turn_thread_id_roundtrip(monkeypatch) -> None:
    """thread_id 透传：第一轮返回的 id 第二轮带上，history 注入选表 prompt。"""

    outputs = [
        TableSelection(tables=["albums"], reason="统计专辑", confidence=0.9),
        SQLDraft(sql="SELECT COUNT(*) AS n FROM albums", explanation="count"),
        FinalAnswer(answer="共 347 张专辑。", evidence=["347"]),
    ]
    _patch_chains(monkeypatch, outputs)

    graph = _build_graph()
    with TestClient(create_app(graph=graph)) as client:
        first = _post(client, "总共有多少张专辑？")
        first_events = _parse_sse(first.text)
        thread_id = json.loads(first_events[0][1])["thread_id"]

        outputs2 = [
            TableSelection(tables=["albums"], reason="追问", confidence=0.9),
            SQLDraft(sql="SELECT MAX(UnitPrice) AS p FROM tracks", explanation="max"),
            FinalAnswer(answer="最贵 1.99。", evidence=["1.99"]),
        ]
        calls2 = _patch_chains(monkeypatch, outputs2)
        second = _post(client, "那最贵的曲目多少钱？", thread_id=thread_id)

    second_events = _parse_sse(second.text)
    meta = json.loads(second_events[0][1])
    assert meta["thread_id"] == thread_id
    assert "result" in [n for n, _ in second_events]
    # 服务端复用同 thread → 作业一的 history 机制生效
    select_prompt = calls2[0][1]["prompt"]
    assert "总共有多少张专辑" in select_prompt


def test_empty_question_rejected() -> None:
    with TestClient(create_app(graph=_build_graph())) as client:
        resp = client.post("/api/chat", json={"question": " "})
    assert resp.status_code == 422


def test_health() -> None:
    with TestClient(create_app(graph=_build_graph())) as client:
        assert client.get("/api/health").json() == {"status": "ok"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


def test_history_endpoint_returns_turns(monkeypatch) -> None:
    """两轮对话后，/api/history 从 checkpoint 还原全部轮次。"""

    graph = _build_graph()
    outputs = [
        TableSelection(tables=["albums"], reason="统计专辑", confidence=0.9),
        SQLDraft(sql="SELECT COUNT(*) AS n FROM albums", explanation="count"),
        FinalAnswer(answer="共 347 张专辑。", evidence=["347"]),
    ]
    _patch_chains(monkeypatch, outputs)
    with TestClient(create_app(graph=graph)) as client:
        first = _post(client, "总共有多少张专辑？")
        thread_id = json.loads(_parse_sse(first.text)[0][1])["thread_id"]

        outputs2 = [
            TableSelection(tables=["albums"], reason="追问", confidence=0.9),
            SQLDraft(sql="SELECT MAX(UnitPrice) AS p FROM tracks", explanation="max"),
            FinalAnswer(answer="最贵 1.99。", evidence=["1.99"]),
        ]
        _patch_chains(monkeypatch, outputs2)
        _post(client, "那最贵的曲目多少钱？", thread_id=thread_id)

        resp = client.get("/api/history", params={"thread_id": thread_id})

    assert resp.status_code == 200
    turns = resp.json()["turns"]
    assert len(turns) == 2
    assert turns[0]["question"] == "总共有多少张专辑？"
    assert turns[1]["question"] == "那最贵的曲目多少钱？"
    assert turns[1]["answer"] == "最贵 1.99。"
