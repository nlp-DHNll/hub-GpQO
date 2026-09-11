"""博查 AI Web Search 客户端。

设计要点：
- 只使用 Bocha 的 summary 字段，不抓全文（README §1.3）。
- 异步 httpx 调用，与 FastAPI 异步任务兼容。
- 响应解析：Bocha 走 Bing-like 结构（data.webPages.value），代码同时兼容
  data.results / top-level results 作为兜底。
- 重试：指数退避 1s/2s/4s，与 DeepSeek 客户端一致。
"""
from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from app.models import SearchResult


class BochaError(Exception):
    """Bocha 调用失败且重试耗尽后抛出。"""


class BochaClient:
    """博查 AI Web Search 客户端。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("BOCHA_API_KEY", "sk-3d2293ad83aa4823a7c7ce8dd5ff8c72")
        self.base_url = (
            base_url or os.getenv("BOCHA_BASE_URL", "https://api.bocha.cn/v1/web-search")
        ).rstrip("/")
        self.timeout = timeout or int(os.getenv("BOCHA_TIMEOUT", "30"))
        self.max_retries = max_retries or int(os.getenv("MAX_RETRIES", "3"))

        if not self.api_key:
            raise ValueError("BOCHA_API_KEY 未设置，请在 .env 中填入")

        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ---------- 公开 API ----------

    async def search(self, query: str, count: int = 5) -> list[SearchResult]:
        """执行一次搜索，返回 SearchResult 列表。

        始终请求 summary=true（仅使用 summary 字段，不抓全文）。
        """
        if not query.strip():
            return []

        payload = {"query": query, "summary": True, "count": count}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        raw = await self._with_retry(self._post, payload, headers)
        return self._parse_results(raw, query=query, count=count)

    # ---------- 内部 ----------

    async def _post(self, payload: dict, headers: dict) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.post(self.base_url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()

    async def _with_retry(self, fn, *args, **kwargs):
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                last_error = e
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    await asyncio.sleep(wait)
        raise BochaError(
            f"Bocha 调用失败，已重试 {self.max_retries} 次：{last_error}"
        ) from last_error

    @staticmethod
    def _extract_items(raw: dict) -> list[dict]:
        """从 Bocha 响应中提取 items 数组。兼容多种返回结构。"""
        # 优先 Bing-like 结构
        data = raw.get("data") if isinstance(raw, dict) else None
        if isinstance(data, dict):
            web = data.get("webPages")
            if isinstance(web, dict) and isinstance(web.get("value"), list):
                return web["value"]
            if isinstance(data.get("results"), list):
                return data["results"]
            if isinstance(data.get("value"), list):
                return data["value"]
        # 顶层 results
        if isinstance(raw, dict) and isinstance(raw.get("results"), list):
            return raw["results"]
        return []

    def _parse_results(
        self, raw: dict, *, query: str, count: int
    ) -> list[SearchResult]:
        items = self._extract_items(raw)
        results: list[SearchResult] = []
        for item in items:
            title = (item.get("name") or item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            summary = (
                item.get("summary")
                or item.get("snippet")
                or ""
            ).strip()
            if not title or not url or not summary:
                # 没有 summary 的结果直接丢弃（README §1.3：只依赖 summary）
                continue
            source = self._domain_from_url(url)
            results.append(
                SearchResult(title=title, url=url, summary=summary, source=source)
            )
            if len(results) >= count:
                break
        return results

    @staticmethod
    def _domain_from_url(url: str) -> str | None:
        try:
            host = urlparse(url).netloc
            return host.lstrip("www.") or None
        except Exception:
            return None


# ---------- 单例 ----------

_client: BochaClient | None = None


def get_bocha() -> BochaClient:
    """获取全局单例 BochaClient。"""
    global _client
    if _client is None:
        _client = BochaClient()
    return _client


async def close_bocha() -> None:
    """关闭全局 httpx 客户端。在 FastAPI 关闭事件中调用。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
