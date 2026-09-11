"""Bocha web-search 客户端。

调用 https://api.bocha.cn/v1/web-search 返回结构化 SourceRef 列表。
未配置 BOCHA_API_KEY 时回落 NoSearch 桩。网络/解析异常不抛致命错，返回 []。
"""
from __future__ import annotations

from typing import Optional

import requests

from . import config
from .schemas import SourceRef


class Searcher:
    """Bocha 搜索封装。"""

    def __init__(self, api_key: Optional[str] = None, endpoint: Optional[str] = None) -> None:
        self._key = api_key if api_key is not None else config.SearchConfig.api_key()
        self.endpoint = endpoint or config.SearchConfig.endpoint

    @classmethod
    def from_env(cls):
        if not config.SearchConfig.api_key():
            return NoSearch()
        return cls()

    def search(self, query: str, count: int = 5) -> list[SourceRef]:
        """执行一次检索，返回网页来源；异常返回 []。"""
        if not self._key:
            return []
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        payload = {"query": query, "summary": True, "count": max(1, int(count))}
        try:
            resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        return self._parse(query, data)

    def _parse(self, query: str, data: dict) -> list[SourceRef]:
        out: list[SourceRef] = []
        try:
            inner = data.get("data") or {}
        except Exception:
            return []
        # Bocha 新版 data.webPages 是 dict，网页在 webPages.value（list）；
        # 旧版/其他源可能是 list 或带 webpages 键——都兼容。
        wp = self._extract_webpages(inner)
        for w in wp:
            url = (w.get("url") or w.get("displayUrl") or "").strip()
            if not url:
                continue
            summary = (w.get("summary") or w.get("content") or "").strip()
            snippet = (w.get("snippet") or "").strip()
            out.append(SourceRef(
                url=url,
                title=(w.get("name") or w.get("title") or "").strip()
                      or (w.get("displayUrl") or "").strip(),
                summary=summary if summary else snippet,
                snippet=snippet or summary,
                source=(w.get("siteName") or w.get("source") or "").strip(),
                publish_time=(w.get("datePublished")
                              or w.get("publish_time") or "").strip(),
                query=query,
            ))
        return out

    @staticmethod
    def _extract_webpages(inner: dict) -> list:
        """从 data 里尽力取出网页 list，兼容不同结构。"""
        if not isinstance(inner, dict):
            return []
        for key in ("webPages", "webpages", "results", "items"):
            obj = inner.get(key)
            if obj is None:
                continue
            if isinstance(obj, dict):
                for sub in ("value", "results", "list", "pages"):
                    if isinstance(obj.get(sub), list):
                        return obj[sub]
                # 兜底：不含 known list 的 dict —— 尝试把值里的 list 收出来
                coll = [v for v in obj.values() if isinstance(v, list)]
                if coll:
                    return coll[0]
                continue
            if isinstance(obj, list):
                return obj
        return []

    def is_stub(self) -> bool:
        return False


class NoSearch(Searcher):
    """供未配 key / 测试用的桩：不联网返回零结果。"""

    def __init__(self) -> None:
        self._key = None
        self.endpoint = config.SearchConfig.endpoint
        self.last_error = "未配置 BOCHA_API_KEY，使用 NoSearch 桩（不联网检索）"

    def search(self, query: str, count: int = 5) -> list[SourceRef]:
        return []

    def is_stub(self) -> bool:
        return True
