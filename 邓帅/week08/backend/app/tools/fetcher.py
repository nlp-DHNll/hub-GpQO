"""网页抓取(httpx)+ 正文提取(trafilatura)。"""
import asyncio
import logging

import httpx
import trafilatura

from app.config import settings

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# 单任务内部并发信号量:按事件循环惰性创建(pytest-asyncio 每测试新 loop)
_semaphores: dict[int, asyncio.Semaphore] = {}


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = id(loop)
    if key not in _semaphores:
        _semaphores[key] = asyncio.Semaphore(settings.concurrency)
    return _semaphores[key]


def extract_text(html: str) -> str | None:
    """提取正文并截断(~8k tokens 近似);提取不到返回 None。"""
    text = trafilatura.extract(
        html, include_comments=False, include_tables=True
    )
    if not text:
        return None
    return text[: settings.page_max_chars]


async def fetch_page(url: str) -> str | None:
    """抓取页面并返回正文;超时 / 非 HTML / 提取失败返回 None(调用方摘要兜底)。"""
    async with _semaphore():
        try:
            async with httpx.AsyncClient(
                timeout=settings.fetch_timeout, follow_redirects=True,
                headers={"User-Agent": UA},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                if "text/html" not in resp.headers.get("content-type", ""):
                    return None
                html = resp.text
        except Exception:
            logger.info("网页抓取失败: %s", url)
            return None
    return extract_text(html)
