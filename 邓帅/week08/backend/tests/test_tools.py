"""工具层单测:bocha mock httpx(成功/重试/放弃)、fetcher 截断与失败路径。"""
import httpx
import pytest

from app.config import settings
from app.tools import bocha, fetcher


def _patch_async_client(monkeypatch, handler):
    """把模块内 httpx.AsyncClient 替换为注入 MockTransport 的版本。"""
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(bocha.httpx, "AsyncClient", factory)


def _bocha_body(urls):
    items = [
        {
            "url": u,
            "name": f"title-{i}",
            "summary": f"summary-{i}",
            "datePublished": "2026-08-01",
        }
        for i, u in enumerate(urls)
    ]
    return {"code": 200, "data": {"webPages": {"value": items}}}


async def test_web_search_success(monkeypatch):
    _patch_async_client(
        monkeypatch,
        lambda request: httpx.Response(200, json=_bocha_body(["https://a.com", "https://b.com"])),
    )
    results = await bocha.web_search("测试查询")
    assert [r["url"] for r in results] == ["https://a.com", "https://b.com"]
    assert results[0]["title"] == "title-0"
    assert results[0]["date_published"] == "2026-08-01"


async def test_web_search_retry_then_success(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500)  # 第一次失败
        return httpx.Response(200, json=_bocha_body(["https://a.com"]))

    _patch_async_client(monkeypatch, handler)
    results = await bocha.web_search("测试查询")
    assert len(calls) == 2
    assert len(results) == 1


async def test_web_search_give_up_after_retry(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    _patch_async_client(monkeypatch, handler)
    results = await bocha.web_search("测试查询")
    assert len(calls) == 2  # 原始 1 次 + 重试 1 次
    assert results == []


# ---------- fetcher ----------

_LONG_HTML = (
    "<html><head><title>长文测试</title></head><body><article><h1>主题</h1>"
    + "<p>这是用于测试正文截断的段落,内容连贯且重复出现,以便超过截断阈值。</p>" * 3000
    + "</article></body></html>"
)


def _patch_fetch_client(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(fetcher.httpx, "AsyncClient", factory)


async def test_fetch_page_truncates(monkeypatch):
    _patch_fetch_client(
        monkeypatch,
        lambda request: httpx.Response(200, text=_LONG_HTML, headers={"content-type": "text/html"}),
    )
    text = await fetcher.fetch_page("https://a.com")
    assert text is not None
    assert len(text) <= settings.page_max_chars


async def test_fetch_page_non_html(monkeypatch):
    _patch_fetch_client(
        monkeypatch,
        lambda request: httpx.Response(200, json={"x": 1}, headers={"content-type": "application/json"}),
    )
    assert await fetcher.fetch_page("https://a.com") is None


async def test_fetch_page_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("boom")

    _patch_fetch_client(monkeypatch, handler)
    assert await fetcher.fetch_page("https://a.com") is None
