"""API 层测试:发起 / SSE 重放 / 取消 / 报告查询 / 404(mock 图节点)。"""
import asyncio
import json

import httpx
import pytest

from app import report as report_mod
from app.api import routes as routes_mod
from app.config import settings
from app.graph import builder as builder_mod
from app.graph import nodes as graph_nodes
from app.main import app
from app.schemas import (
    Finding,
    FindingsOutput,
    PlanOutput,
    ReflectOutput,
    SelectOutput,
)


class _Msg:
    def __init__(self, content):
        self.content = content


def _stub_graph(monkeypatch):
    """打桩全部 LLM/网络依赖,图全路径跑通。"""

    async def fake_web_search(query, retry=1):
        return [
            {
                "url": "https://example.com/1",
                "title": "文章一",
                "summary": "摘要内容一",
                "date_published": "2026-08-01",
            }
        ]

    async def fake_fetch_page(url):
        return "正文内容,包含重要事实。"

    async def fake_structured(schema, prompt, retry=1):
        if schema is PlanOutput:
            return PlanOutput(sub_questions=["子问题一", "子问题二", "子问题三"])
        if schema is SelectOutput:
            return SelectOutput(urls=["https://example.com/1"])
        if schema is FindingsOutput:
            return FindingsOutput(
                findings=[Finding(point="事实一", quote="重要事实", url="https://example.com/1")]
            )
        if schema is ReflectOutput:
            return ReflectOutput(sufficient=True, gaps="", new_queries=[])
        raise AssertionError(schema)

    class _FakeLLM:
        async def ainvoke(self, messages):
            return _Msg(
                "## 摘要\n\n摘要。\n\n## 分节正文\n\n- 事实 [1]\n\n"
                "## 关键结论\n\n- 结论 [1]\n\n## 遗留问题\n\n- 无"
            )

    monkeypatch.setattr(graph_nodes, "web_search", fake_web_search)
    monkeypatch.setattr(graph_nodes, "fetch_page", fake_fetch_page)
    monkeypatch.setattr(graph_nodes, "_structured", fake_structured)
    monkeypatch.setattr(graph_nodes, "get_llm", lambda temperature=0.2: _FakeLLM())


@pytest.fixture
async def client(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(report_mod, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(routes_mod, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(builder_mod, "CHECKPOINT_DB", tmp_path / "cp.db")
    routes_mod.TASKS.clear()
    transport = httpx.ASGITransport(app=app)
    async with builder_mod.open_checkpointer() as cp:
        app.state.checkpointer = cp
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


async def _wait_status(client, task_id, terminal, timeout=10.0):
    for _ in range(int(timeout / 0.05)):
        r = await client.get(f"/api/research/{task_id}")
        if r.json().get("status") in terminal:
            return r.json()
        await asyncio.sleep(0.05)
    raise AssertionError(f"等待状态 {terminal} 超时")


async def test_research_full_flow(client, monkeypatch):
    _stub_graph(monkeypatch)
    r = await client.post("/api/research", json={"topic": "测试研究主题"})
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    final = await _wait_status(client, task_id, {"completed", "incomplete"})
    assert final["status"] == "completed"

    # 报告列表与详情
    r = await client.get("/api/reports")
    assert any(i["task_id"] == task_id for i in r.json()["items"])
    r = await client.get(f"/api/reports/{task_id}")
    assert r.status_code == 200
    assert "## 来源列表" in r.json()["report_md"]
    assert r.json()["process"]["stats"]["rounds"] == 1


async def test_sse_replays_buffer_for_finished_task(client, monkeypatch):
    _stub_graph(monkeypatch)
    task_id = (await client.post("/api/research", json={"topic": "SSE 测试"})).json()["task_id"]
    await _wait_status(client, task_id, {"completed", "incomplete"})

    events = []
    async with client.stream("GET", f"/api/research/{task_id}/events") as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    types = [e["type"] for e in events]
    assert "plan" in types and "report_done" in types
    # 事件 id 递增
    ids = [e["id"] for e in events]
    assert ids == sorted(ids)


async def test_cancel_running_task(client, monkeypatch):
    _stub_graph(monkeypatch)
    # 放慢 search 节点,留出取消窗口
    async def slow_search(state):
        await asyncio.sleep(5)
        return {}

    monkeypatch.setattr(builder_mod, "search_node", slow_search)
    task_id = (await client.post("/api/research", json={"topic": "取消测试"})).json()["task_id"]
    await asyncio.sleep(0.2)  # 等 plan 完成、进入 search

    r = await client.delete(f"/api/research/{task_id}")
    assert r.status_code == 200
    final = await _wait_status(client, task_id, {"aborted"})
    assert final["status"] == "aborted"
    # 取消后不生成报告
    r = await client.get(f"/api/reports/{task_id}")
    assert r.status_code == 404
    # 再次取消:幂等
    r = await client.delete(f"/api/research/{task_id}")
    assert r.json()["status"] == "aborted"


async def test_unknown_task_404(client):
    r = await client.get("/api/research/nonexistent/events")
    assert r.status_code == 404
    r = await client.get("/api/reports/nonexistent")
    assert r.status_code == 404
    r = await client.delete("/api/research/nonexistent")
    assert r.status_code == 404


async def test_topic_validation(client):
    r = await client.post("/api/research", json={"topic": "a"})
    assert r.status_code == 422
