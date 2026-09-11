from fastapi.testclient import TestClient

from backend import config, storage
from backend.app import app
from backend.auth import hash_password
from backend.exporters import to_html, to_markdown
from backend.models import Conclusion, ReportContent, ResearchRequest, Section, Source, Status
from backend.tools import _plain_text, _public_http_url


def authenticated_client(monkeypatch):
    config.SHARED_PASSWORD_HASH = hash_password("demo-pass", iterations=1_000)
    monkeypatch.setattr("backend.app.enqueue", lambda _: None)
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"password": "demo-pass"})
    assert response.status_code == 200
    return client


def test_auth_create_cancel_delete(monkeypatch):
    client = authenticated_client(monkeypatch)
    created = client.post("/api/research", json={"topic": "企业 AI Agent 研究", "depth": "quick"})
    assert created.status_code == 202
    rid = created.json()["research_id"]
    try:
        record = client.get(f"/api/research/{rid}")
        assert record.status_code == 200
        assert record.json()["limits"]["max_searches"] == 3
        cancelled = client.post(f"/api/research/{rid}/cancel")
        assert cancelled.status_code == 202
        assert cancelled.json()["status"] == "cancelled"
    finally:
        storage.delete_one(rid)


def test_version_chain():
    first_id, second_id = "test-v1", "test-v2"
    try:
        first = storage.create(first_id, ResearchRequest(topic="版本测试"))
        first.status = Status.completed
        storage.save(first)
        second = storage.create(second_id, ResearchRequest(topic="版本测试", parent_id=first_id, follow_up="补充案例"))
        assert second.version == 2
        assert second.root_id == first_id
        assert [item.version for item in storage.versions_for(first_id)] == [1, 2]
    finally:
        storage.delete_one(first_id)
        storage.delete_one(second_id)


def test_export_and_ssrf_guards():
    rec = storage.create("test-export", ResearchRequest(topic="导出测试"))
    try:
        rec.status = Status.completed
        rec.report = ReportContent(title="测试报告", summary="摘要", sections=[Section(heading="分析", body="正文")],
                                   key_conclusions=[Conclusion(text="推断项", is_model_inference=True)])
        rec.sources = [Source(url="https://example.com", title="Example", accessed_at="2026-09-10")]
        assert "模型推断" in to_markdown(rec)
        assert "<!doctype html>" in to_html(rec)
        assert not _public_http_url("http://127.0.0.1/private")
        assert "你好" in _plain_text("<script>x</script><p>你好</p>")
    finally:
        storage.delete_one("test-export")
