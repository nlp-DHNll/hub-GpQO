"""多源配置与受限抓取

运行（不需要 pytest）::

    python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from esgtender import (  # noqa: E402
    cli,
    crawl,
    dedup,
    docx_export,
    env,
    extract,
    netguard,
    notify,
    package,
    pipeline,
    presets,
    render,
    search,
    sources,
    store,
    triage,
)


class TestSources(unittest.TestCase):
    def _cfg(self):
        return {
            "defaults": {"enabled": False, "max_site_queries": 2},
            "sources": [
                {"id": "a", "mode": "search_site", "domains": ["a.gov.cn"], "weight": 1, "keywords": ["碳核查", "碳盘查"]},
                {"id": "b", "mode": "search_site", "domains": ["b.cn"], "weight": 3, "keywords": ["碳足迹"]},
                {"id": "c", "mode": "crawl", "list_url": "https://c.cn/list", "enabled": False},
            ],
        }

    def test_invalid_mode_rejected(self):
        with self.assertRaises(sources.SourceError):
            sources._validate({"sources": [{"id": "x", "mode": "magic"}]})

    def test_duplicate_id_rejected(self):
        with self.assertRaises(sources.SourceError):
            sources._validate(
                {"sources": [{"id": "x", "mode": "api"}, {"id": "x", "mode": "api"}]}
            )

    def test_search_site_requires_domains(self):
        with self.assertRaises(sources.SourceError):
            sources._validate({"sources": [{"id": "x", "mode": "search_site"}]})

    def test_force_ignores_global_default_but_not_explicit_false(self):
        cfg = self._cfg()
        self.assertEqual(sources.enabled(cfg), [])
        active = {item["id"] for item in sources.enabled(cfg, include_crawl=True, force=True)}
        self.assertEqual(active, {"a", "b"})  # c 显式 enabled:false

    def test_site_queries_ranked_by_weight_and_capped(self):
        cfg = self._cfg()
        items = sources.site_queries(
            cfg, fallback_keywords=["碳盘查"], suffix="招标公告", force=True
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["source_id"], "b")  # 权重 3 优先
        self.assertIn("site:b.cn", items[0]["query"])
        self.assertIn("招标公告", items[0]["query"])

    def test_offline_config_loads(self):
        cfg = sources.load()
        self.assertGreaterEqual(len(cfg.get("sources") or []), 1)


class TestCrawl(unittest.TestCase):
    HTML = """
    <html><body>
      <a href="/a/1.html">某市碳盘查服务项目招标公告</a>
      <a href="/login">登录</a>
      <a href="/a/2.html">短标题</a>
      <a href="https://other.example.com/x.html">某省碳核查项目采购公告</a>
      <a href="/a/1.html">某市碳盘查服务项目招标公告</a>
      <a href="/a/3.html">某园区绿色工厂评价服务采购项目</a>
      <a href="#top">回到顶部</a>
      <a href="/a/site.css">样式</a>
    </body></html>
    """

    def test_extract_links_filters_nav_offsite_and_dupes(self):
        links = crawl.extract_links(
            self.HTML, "https://ggzy.example.gov.cn/list.html", ["碳", "绿色"]
        )
        self.assertEqual(
            [item["url"] for item in links],
            [
                "https://ggzy.example.gov.cn/a/1.html",
                "https://ggzy.example.gov.cn/a/3.html",
            ],
        )

    def test_crawl_source_does_not_invent_publish_date(self):
        source = {"id": "x", "name": "X 交易中心", "list_url": "https://ggzy.example.gov.cn/list.html"}
        hits = crawl.crawl_source(
            source,
            keywords=["碳", "绿色"],
            fetcher=lambda url: "" if url.endswith("robots.txt") else self.HTML,
        )
        self.assertEqual(len(hits), 2)
        # 列表页没有发布日期，必须留空（由上层计入 unknown_date），不能填今天
        self.assertTrue(all(hit.published == "" for hit in hits))
        self.assertTrue(all(hit.provider == "crawl" for hit in hits))

    def test_robots_denied_raises(self):
        source = {"id": "x", "list_url": "https://ggzy.example.gov.cn/list.html"}
        with self.assertRaises(crawl.CrawlError):
            crawl.crawl_source(
                source,
                keywords=["碳"],
                fetcher=lambda url: "User-agent: *\nDisallow: /\n" if url.endswith("robots.txt") else self.HTML,
            )

    def test_pagination_only_when_page_param_configured(self):
        calls: list[str] = []

        def fetcher(url: str) -> str:
            calls.append(url)
            return "" if url.endswith("robots.txt") else self.HTML

        source = {
            "id": "x",
            "list_url": "https://ggzy.example.gov.cn/list.html?cat=1",
            "max_pages": 2,
        }
        crawl.crawl_source(source, keywords=["碳"], fetcher=fetcher, sleep=lambda _: None)
        self.assertEqual(len([c for c in calls if "list.html" in c]), 1)

        source["page_param"] = "page"
        calls.clear()
        crawl.crawl_source(source, keywords=["碳"], fetcher=fetcher, sleep=lambda _: None)
        self.assertIn("https://ggzy.example.gov.cn/list.html?cat=1&page=2", calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
