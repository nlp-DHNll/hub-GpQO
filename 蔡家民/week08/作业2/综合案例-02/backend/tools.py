# -*- coding: utf-8 -*-
"""Bocha 搜索与安全的公开网页正文提取。"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html import unescape
from urllib.parse import urlparse

import httpx

from . import config

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".local"):
        return False
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        addresses = [ipaddress.ip_address(item[4][0]) for item in infos]
        return bool(addresses) and all(a.is_global for a in addresses)
    except (socket.gaierror, ValueError):
        return False


def _plain_text(html: str) -> str:
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    return _SPACE_RE.sub(" ", unescape(_TAG_RE.sub(" ", html))).strip()[: config.MAX_PAGE_CHARS]


async def fetch_public_page(url: str) -> tuple[str, str]:
    """只读取公网 HTTP(S)，禁重定向以避免 SSRF 跳转。"""
    if not _public_http_url(url):
        return "", "failed"
    try:
        async with httpx.AsyncClient(timeout=config.FETCH_PAGE_TIMEOUT, follow_redirects=False) as client:
            response = await client.get(url, headers={"User-Agent": "DeepResearchDemo/1.0"})
        if response.status_code != 200 or "text/html" not in response.headers.get("content-type", ""):
            return "", "failed"
        text = _plain_text(response.text)
        return (text, "full") if len(text) >= 200 else ("", "failed")
    except (httpx.HTTPError, UnicodeError):
        return "", "failed"


async def web_search(query: str) -> list[dict]:
    if not config.BOCHA_API_KEY:
        raise RuntimeError("未配置 BOCHA_API_KEY")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.bocha.cn/v1/web-search",
            headers={"Authorization": f"Bearer {config.BOCHA_API_KEY}"},
            json={"query": query, "summary": True, "count": config.BOCHA_SEARCH_COUNT},
        )
        response.raise_for_status()
        pages = response.json().get("data", {}).get("webPages", {}).get("value", [])

    results = [
        {
            "title": page.get("name") or "",
            "url": page.get("url") or "",
            "snippet": (page.get("summary") or page.get("snippet") or "")[:1000],
            "site_name": page.get("siteName") or "",
            "date": page.get("datePublished") or page.get("dateLastCrawled") or "",
            "content": "",
            "extraction_status": "summary",
        }
        for page in pages
        if page.get("url")
    ]
    fetched = await asyncio.gather(*(fetch_public_page(item["url"]) for item in results[:5]))
    for item, (content, status) in zip(results, fetched):
        item["content"] = content or item["snippet"]
        item["extraction_status"] = status if content else "summary"
    return results


if __name__ == "__main__":
    assert not _public_http_url("http://127.0.0.1/admin")
    assert "你好" in _plain_text("<p>你好</p>")
    print("tools 安全自检 OK")
