"""DDGS 适配器和月报查询的回归测试。"""

import json
import unittest
from unittest.mock import Mock, patch

import httpx
from ddgs.exceptions import DDGSException, TimeoutException

from backend.clients.ddgs_search import DDGSSearchClient
from backend.clients.disclosures import HKEX_QUERY, SSE_QUERY, DisclosureClient
from backend.data_models import SearchHit, SourcePage
from backend.enums import Topic
from backend.errors import RunFailure, SourceRejected
from backend.tools.filter_sources import filter_sources
from backend.tools.search import search_sources
from backend.tools.source_catalog import ENERGY_INDEX


class DDGSSearchTests(unittest.TestCase):
    def test_converts_search_results_to_hits(self) -> None:
        with patch("backend.clients.ddgs_search.DDGS") as ddgs:
            ddgs.return_value.text.return_value = [
                {"title": "报告 &amp; 公告", "href": "https://www.csec.com/report", "body": "摘要"},
                {"title": "缺少网址"},
                {"title": None, "href": "https://www.csec.com/untitled"},
            ]
            hits = DDGSSearchClient().search("中国神华", Topic.COMPANY)

        self.assertEqual(hits, [SearchHit(Topic.COMPANY, "报告 & 公告", "https://www.csec.com/report", "摘要")])

    def test_empty_results_allow_supplemental_search(self) -> None:
        with patch("backend.clients.ddgs_search.DDGS") as ddgs:
            ddgs.return_value.text.side_effect = DDGSException("No results found.")
            hits = DDGSSearchClient().search("无资料", Topic.PEERS)

        self.assertEqual(hits, [])
        self.assertEqual(ddgs.return_value.text.call_count, 1)

    def test_timeout_retries_once(self) -> None:
        retry = Mock()
        with patch("backend.clients.ddgs_search.DDGS") as ddgs, patch("backend.clients.ddgs_search.sleep"):
            ddgs.return_value.text.side_effect = [TimeoutException("timed out"), []]
            hits = DDGSSearchClient().search("中国神华", Topic.COMPANY, on_retry=retry)

        self.assertEqual(hits, [])
        self.assertEqual(ddgs.return_value.text.call_count, 2)
        retry.assert_called_once()

    def test_query_uses_target_month_and_changes_on_supplement(self) -> None:
        client = Mock()
        client.search.return_value = []
        logger = Mock()
        for supplement in (False, True):
            search_sources("2026-10", (Topic.COMPANY,), supplement, logger, client=client)

        queries = [call.args[0] for call in client.search.call_args_list]
        self.assertTrue(all("2026年10月" in query for query in queries))
        self.assertNotEqual(*queries)

    def test_official_search_continues_with_ddgs_and_one_catalog_down(self) -> None:
        client = Mock()
        client.search.side_effect = RunFailure("DDGS 网页搜索失败")
        pages = Mock()
        current = "https://www.nea.gov.cn/20261021/notice/c.html"
        html = (
            f'<a href="{current}">煤电与新能源融合</a>'
            '<a href="https://www.nea.gov.cn/20260921/notice/c.html">煤电旧消息</a>'
            '<a href="https://example.invalid/20261021/notice/">煤电消息</a>'
        )
        def fetch(url):
            if url == ENERGY_INDEX:
                return SourcePage(url, html.encode(), "utf-8")
            raise SourceRejected("原文无法访问")

        pages.fetch.side_effect = fetch
        topics = (Topic.POLICY, Topic.INDUSTRY, Topic.COMPANY)
        logger = Mock()
        hits = search_sources("2026-10", topics, False, logger, client=client, page_client=pages)

        self.assertEqual(pages.fetch.call_count, 4)
        self.assertEqual([(hit.topic, hit.url) for hit in hits], [
            (Topic.POLICY, current),
            (Topic.INDUSTRY, current),
        ])
        self.assertTrue(all(hit.provider == "nea" for hit in hits))
        self.assertTrue(any(
            call.args == ("search_provider_failed",) and call.kwargs["details"]["provider"] == "mee"
            for call in logger.record.call_args_list
        ))

    def test_disclosures_without_ddgs_only_accept_verified_html(self) -> None:
        def handle(request):
            endpoint = str(request.url).partition("?")[0]
            if endpoint == SSE_QUERY:
                self.assertEqual(request.url.params["endDate"], "2024-02-29")
                return httpx.Response(200, json={"pageHelp": {"data": [{
                    "TITLE": "中国神华公告", "SECURITY_CODE": "601088", "SSEDATE": "2024-02-28",
                    "URL": "/notice.pdf",
                }]}})
            self.assertEqual(endpoint, HKEX_QUERY)
            self.assertEqual(request.url.params["fromDate"], "20240201")
            self.assertEqual(request.url.params["toDate"], "20240229")
            return httpx.Response(200, json={"result": json.dumps([{
                "TITLE": "中国神华公司治理", "STOCK_CODE": "01088", "DATE_TIME": "28/02/2024 19:30",
                "FILE_LINK": "/article.htm",
            }, {
                "TITLE": "上月旧公告", "STOCK_CODE": "01088", "DATE_TIME": "28/01/2024 19:30",
                "FILE_LINK": "/old.htm",
            }])})

        logger = Mock()
        with httpx.Client(transport=httpx.MockTransport(handle)) as http:
            hits = search_sources(
                "2024-02", (Topic.COMPANY,), False, logger, client=None, disclosures=DisclosureClient(http),
            )
        self.assertEqual([hit.provider for hit in hits], ["sse", "hkex"])

        def fetch(url):
            if url.endswith(".pdf"):
                raise SourceRejected("候选链接不是网页")
            article = '<meta name="PubDate" content="2024-02-28"><article><p>' + "公司治理资料" * 20
            return SourcePage(url, article.encode(), "utf-8")

        pages = Mock()
        pages.fetch.side_effect = fetch
        sources = filter_sources("2024-02", hits, [], logger, client=pages)
        self.assertEqual([source.title for source in sources], ["中国神华公司治理"])
        logger.record.assert_any_call("source_provider_verified", details={"counts": {"sse": 0, "hkex": 1}})
