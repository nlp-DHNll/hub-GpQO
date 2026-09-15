"""Bocha AI web-search 封装(httpx)。"""
import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BOCHA_URL = "https://api.bocha.cn/v1/web-search"


def _parse_results(data: dict) -> list[dict]:
    """从 Bocha 响应提取统一结构:[{url, title, summary, date_published}]。"""
    items = data.get("data", {}).get("webPages", {}).get("value", [])
    return [
        {
            "url": item.get("url", ""),
            "title": item.get("name", ""),
            "summary": item.get("summary") or "",
            "date_published": item.get("datePublished") or "",
        }
        for item in items
    ]


async def web_search(query: str, retry: int = 1) -> list[dict]:
    """执行一次检索(count=10、summary=true),失败重试 retry 次后放弃。

    放弃时返回空列表:调用方将该查询记为失败并继续流程,不中断任务。
    """
    payload = {"query": query, "summary": True, "count": 10}
    headers = {"Authorization": f"Bearer {settings.bocha_api_key}"}
    data: dict | None = None
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(retry + 1):
            try:
                resp = await client.post(BOCHA_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception:
                if attempt == retry:
                    logger.warning("bocha 搜索失败(含重试): %s", query)
                    return []
                await asyncio.sleep(0.5)
    if data is None:
        return []
    return _parse_results(data)
