"""Web API 测试：用 TestClient 走真实 FastAPI 路由，LLM 仍然 mock。"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from sql_agent.llm import StructuredAgent
from sql_agent.models import FinalAnswer, SQLDraft, TableSelection
from sql_agent.webapp.server import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _patch_agents(monkeypatch, outputs):
    calls = []

    async def fake_ainvoke(self, text):
        calls.append((self.name, text))
        return outputs[len(calls) - 1]

    monkeypatch.setattr(StructuredAgent, "ainvoke", fake_ainvoke)
    return calls


def test_index_and_static_assets(client: TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert "Chinook SQL Agent" in index.text
    assert "/static/app.js" in index.text

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "sendQuestion" in script.text


def test_health(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["tables"] == 11
    assert payload["has_api_key"] is True
    assert payload["model"]


def test_query_returns_answer_sql_and_rows(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    outputs = [
        TableSelection(tables=["albums"], reason="统计专辑数量", confidence=0.95),
        SQLDraft(sql="SELECT COUNT(*) AS n FROM albums", explanation="count albums"),
        FinalAnswer(answer="共 347 张专辑。", evidence=["347"]),
    ]
    calls = _patch_agents(monkeypatch, outputs)

    response = client.post("/api/query", json={"question": "总共有多少张专辑？"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["answer"] == "共 347 张专辑。"
    assert payload["sql"] == "SELECT COUNT(*) AS n FROM albums"
    assert payload["tables"] == ["albums"]
    assert payload["row_count"] == 1
    assert payload["columns"] == ["n"]
    assert payload["rows"] == [["347"]]
    assert payload["elapsed_ms"] >= 0
    assert len(calls) == 3


def test_query_without_api_key_returns_503(client: TestClient, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    response = client.post("/api/query", json={"question": "总共有多少张专辑？"})

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_query_rejects_blank_question(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    response = client.post("/api/query", json={"question": "   "})

    assert response.status_code == 422
    assert "不能为空" in response.json()["detail"]


def test_query_failure_is_reported_in_json(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def boom(self, text):
        raise RuntimeError("模型调用失败")

    monkeypatch.setattr(StructuredAgent, "ainvoke", boom)

    response = client.post("/api/query", json={"question": "总共有多少张专辑？"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert "处理失败" in payload["answer"]
    assert "模型调用失败" in (payload["error"] or "")
