"""检索（一）：经 MCP 协议直连智谱 web_search_prime。

与无脚本版智能体用的是同一个服务、同一把 key，两版的差异才只来自脚本化本身。
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

import httpx

from . import config

ENDPOINT = "https://open.bigmodel.cn/api/mcp/web_search_prime/mcp"
RECENTRIES = ("oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit")
"""时间过滤档位；没有「近两年」这一档，更早的要靠 noLimit 召回后逐条看发布日期。"""

_SEARCH_LOCK = threading.Lock()
"""智谱搜索在进程内串行：账户有速率限制，并发超过四路就返回 429。"""

_MAX_ATTEMPTS = 5


_ENGINE_DATE = re.compile(r"^\s*(.+?)\s*—\s*")
"""搜索摘要开头的「2026年11月2日 —」「7小时前 —」：这是索引时间，不是发布日期。"""

Hit = dict[str, Any]


def decode_message(text: str) -> dict[str, Any]:
    """从一次响应里取出 JSON-RPC 消息：响应是 SSE 时取最后一条 data 行，否则整段就是 JSON。"""
    data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    message: dict[str, Any] = json.loads(data_lines[-1] if data_lines else text)
    return message


def decode_hits(text: str) -> list[Hit]:
    """把 tools/call 的响应解成命中列表：content 里的 text 是双重 JSON 编码的字符串。"""
    result = decode_message(text).get("result", {})
    if result.get("isError"):
        raise RuntimeError("智谱搜索返回错误")
    content = result.get("content") or []
    if not content:
        return []
    inner = json.loads(content[0]["text"])
    items = json.loads(inner) if isinstance(inner, str) else inner
    hits: list[Hit] = []
    for item in items:
        snippet = str(item.get("content") or "")
        engine_date = _ENGINE_DATE.match(snippet)
        hits.append(
            {
                "url": str(item.get("link") or ""),
                "title": str(item.get("title") or "").strip(),
                "snippet": snippet,
                "engine_date": engine_date[1].strip() if engine_date else None,
            }
        )
    return [hit for hit in hits if hit["url"].startswith(("http://", "https://"))]


class ZhipuSearch:
    """一次会话：initialize 拿到 Mcp-Session-Id，之后的请求都带上它。"""

    def __init__(self, key: str | None = None) -> None:
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": key or config.ZHIPU_API_KEY,
        }
        self._client: httpx.Client | None = None

    def __enter__(self) -> ZhipuSearch:
        client = httpx.Client(timeout=30)
        response = client.post(
            ENDPOINT,
            headers=self._headers,
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "esgscript", "version": "0.1.0"},
                },
            },
        )
        response.raise_for_status()
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._headers["Mcp-Session-Id"] = session_id
        client.post(
            ENDPOINT, headers=self._headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        self._client = client
        return self

    def __exit__(self, *_: object) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def search(
        self,
        query: str,
        *,
        recency: str = "noLimit",
        location: str = "cn",
        size: str = "medium",
        domain: str | None = None,
    ) -> list[Hit]:
        """一次检索，返回去重前的命中列表。"""
        if self._client is None:
            raise RuntimeError("ZhipuSearch 须用 with 语句进入后再检索")
        arguments: dict[str, Any] = {
            "search_query": query,
            "search_recency_filter": recency,
            "content_size": size,
            "location": location,
        }
        if domain:
            arguments["search_domain_filter"] = domain
        body = {
            "jsonrpc": "2.0",
            "id": "search",
            "method": "tools/call",
            "params": {"name": "web_search_prime", "arguments": arguments},
        }
        for attempt in range(_MAX_ATTEMPTS):
            with _SEARCH_LOCK:
                response = self._client.post(ENDPOINT, headers=self._headers, json=body)
            response.raise_for_status()
            try:
                return decode_hits(response.text)
            except RuntimeError:  # 多半是 429 速率限制：退避后重试
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
                time.sleep(2.0 * (attempt + 1))
        raise RuntimeError("智谱搜索重试后仍失败")
