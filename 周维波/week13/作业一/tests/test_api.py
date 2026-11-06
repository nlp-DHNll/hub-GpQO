"""API 测试：用 Fake 图隔离 LLM，验证路由、契约与 SSE 帧格式。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import sql_agent.api.app as app_module
from sql_agent.api.app import app
from sql_agent.models import FinalAnswer, WorkflowOutput

CLIENT = TestClient(app)


class FakeGraph:
    def __init__(self, result: dict, events: list[dict]) -> None:
        self.result = result
        self.events = events

    async def run_full(self, question: str) -> dict:
        return self.result

    async def stream(self, question: str):
        for event in self.events:
            yield event


class BoomGraph:
    async def run_full(self, question: str) -> dict:
        raise RuntimeError("boom")

    async def stream(self, question: str):
        raise RuntimeError("boom")
        yield {}


def _payload(answer: str = "共有 347 张专辑。") -> dict:
    output = WorkflowOutput(
        question="总共有多少张专辑？",
        answer=answer,
        sql="SELECT COUNT(*) AS total FROM albums",
        tables=["albums"],
        row_count=1,
        evidence=["347"],
    )
    return {
        "output": output,
        "columns": ["total"],
        "rows": [["347"]],
        "stages": [
            {
                "node": "select_tables",
                "label": "选择数据表",
                "elapsed_ms": 12.5,
                "detail": {"tables": ["albums"]},
            }
        ],
    }


def _events() -> list[dict]:
    return [
        {"type": "stage_start", "node": "select_tables", "label": "选择数据表"},
        {
            "type": "stage_end",
            "node": "select_tables",
            "label": "选择数据表",
            "detail": {"tables": ["albums"]},
        },
        {
            "type": "final",
            "output": _payload()["output"].model_dump(),
            "columns": ["total"],
            "rows": [["347"]],
            "stages": _payload()["stages"],
        },
    ]


@pytest.fixture()
def fake_graph(monkeypatch: pytest.MonkeyPatch) -> FakeGraph:
    graph = FakeGraph(_payload(), _events())
    monkeypatch.setattr(app_module, "get_agent_graph", lambda: graph)
    return graph


def test_index_serves_web_page() -> None:
    response = CLIENT.get("/")
    assert response.status_code == 200
    assert "Chinook SQL Agent" in response.text
    assert "/api/query/stream" in response.text


def test_health() -> None:
    response = CLIENT.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_schema_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = SimpleNamespace(row_count=347, columns=[SimpleNamespace(name="AlbumId")])
    catalog = SimpleNamespace(
        db_path=Path("chinook.db"),
        table_names=["albums"],
        _tables={"albums": profile},
    )
    monkeypatch.setattr(app_module, "get_catalog", lambda: catalog)

    response = CLIENT.get("/api/schema")
    assert response.status_code == 200
    data = response.json()
    assert data["database"] == "chinook.db"
    assert data["tables"] == [
        {"name": "albums", "rows": 347, "columns": ["AlbumId"]}
    ]


def test_query_endpoint_returns_contract(fake_graph: FakeGraph) -> None:
    response = CLIENT.post("/api/query", json={"question": "总共有多少张专辑？"})
    assert response.status_code == 200

    data = response.json()
    assert data["output"]["answer"] == "共有 347 张专辑。"
    assert data["output"]["sql"] == "SELECT COUNT(*) AS total FROM albums"
    assert data["output"]["row_count"] == 1
    assert data["columns"] == ["total"]
    assert data["rows"] == [["347"]]
    assert data["elapsed_ms"] >= 0


def test_query_rejects_empty_question() -> None:
    response = CLIENT.post("/api/query", json={"question": ""})
    assert response.status_code == 422


def test_query_reports_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "get_agent_graph", lambda: BoomGraph())
    response = CLIENT.post("/api/query", json={"question": "x"})
    assert response.status_code == 500
    assert "boom" in response.json()["detail"]


def test_stream_endpoint_emits_sse_frames(fake_graph: FakeGraph) -> None:
    response = CLIENT.post("/api/query/stream", json={"question": "总共有多少张专辑？"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    frames = [f for f in response.text.split("\n\n") if f.strip()]
    payloads = [json.loads(frame.split("data:", 1)[1].strip()) for frame in frames]

    assert payloads[0]["type"] == "stage_start"
    assert payloads[0]["node"] == "select_tables"
    assert payloads[-1]["type"] == "final"
    assert payloads[-1]["output"]["answer"] == "共有 347 张专辑。"
    assert payloads[-1]["rows"] == [["347"]]
    assert payloads[-1]["elapsed_ms"] >= 0


def test_stream_reports_error_as_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "get_agent_graph", lambda: BoomGraph())
    response = CLIENT.post("/api/query/stream", json={"question": "x"})
    assert response.status_code == 200

    frames = [f for f in response.text.split("\n\n") if f.strip()]
    last = json.loads(frames[-1].split("data:", 1)[1].strip())
    assert last["type"] == "error"
    assert "boom" in last["message"]
