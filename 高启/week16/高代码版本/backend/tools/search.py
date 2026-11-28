"""按主题检索公开网页，合并各入口发现的候选资料。"""

from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial

from ..clients.ddgs_search import DDGSSearchClient
from ..clients.disclosures import HKEX_SECURITIES, DisclosureClient
from ..clients.source_pages import SourcePageClient
from ..data_models import SearchHit
from ..enums import Topic
from ..errors import RunFailure, SourceRejected
from ..log.run_logger import RunLogger
from .source_catalog import CATALOGS, catalog_hits

QUERIES = {
    Topic.POLICY: ("ESG 可持续披露 政策 标准", "煤电 碳排放 政策 OR ISSB 披露"),
    Topic.INDUSTRY: ("煤炭 电力 绿色低碳 行业动态", "煤电 节能减排 OR 煤矿 安全生产"),
    Topic.COMPANY: ("中国神华 ESG OR 环境 OR 安全", "中国神华 公告 绿色 OR 可持续发展"),
    Topic.PEERS: ("中煤能源 OR 兖矿能源 OR 华能国际 ESG", "煤炭 煤电 上市公司 低碳 可持续发展"),
}


def _ddgs_hits(
    client: DDGSSearchClient, month: str, topics: tuple[Topic, ...], supplement: bool, logger: RunLogger,
) -> list[SearchHit]:
    year, number = month.split("-")
    month_term = f"{year}年{int(number)}月"
    hits = []
    for topic in topics:
        query = f"{QUERIES[topic][int(supplement)]} {month_term}"
        logger.record("search_query", details={"topic": topic, "query": query})
        try:
            results = client.search(
                query, topic, on_retry=lambda reason, topic=topic: logger.record(
                    "search_retry", details={"topic": topic, "reason": reason}
                ),
            )
        except RunFailure as error:
            logger.record("search_provider_failed", level="WARNING", details={
                "provider": "ddgs", "target": topic, "reason": str(error),
            })
            continue
        hits.extend(replace(hit, provider="ddgs") for hit in results)
    return hits


def _official_queries(
    month: str, topics: tuple[Topic, ...], pages: SourcePageClient | None,
    disclosures: DisclosureClient | None,
) -> list[tuple[str, str, Callable[[], list[SearchHit]]]]:
    """每次调用查询同一月份，按入口和证券代码定位单项失败。"""
    queries = []
    if pages is not None:
        for provider, (url, supported, _) in CATALOGS.items():
            if any(topic in topics for topic in supported):
                queries.append((provider, url, partial(catalog_hits, provider, month, topics, pages)))
    if disclosures is not None:
        if Topic.COMPANY in topics:
            queries.append(("sse", "601088", partial(disclosures.sse, month)))
        for topic, code, stock_id in HKEX_SECURITIES:
            if topic in topics:
                queries.append(("hkex", code, partial(disclosures.hkex, month, topic, code, stock_id)))
    return queries


def search_sources(
    month: str,
    topics: tuple[Topic, ...],
    supplement: bool,
    logger: RunLogger,
    *,
    client: DDGSSearchClient | None,
    page_client: SourcePageClient | None = None,
    disclosures: DisclosureClient | None = None,
) -> list[SearchHit]:
    """首轮合并各入口。补搜只改变 DDGS 关键词，避免重复请求固定的官网栏目。"""
    queries = [] if supplement else _official_queries(month, topics, page_client, disclosures)
    results: dict[str, set[str]] = defaultdict(set)
    hits = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        pending = [(provider, target, pool.submit(query)) for provider, target, query in queries]
        if client is not None:
            web_hits = _ddgs_hits(client, month, topics, supplement, logger)
            results["ddgs"].update(hit.url for hit in web_hits)
            hits.extend(web_hits)
        for provider, target, future in pending:
            urls = results[provider]
            try:
                candidates = future.result()
            except SourceRejected as error:
                logger.record("search_provider_failed", level="WARNING", details={
                    "provider": provider, "target": target, "reason": str(error),
                })
                continue
            urls.update(hit.url for hit in candidates)
            hits.extend(candidates)
    for provider, urls in results.items():
        logger.record("search_provider_results", details={
            "provider": provider, "candidates": len(urls),
            "pdf": sum(url.partition("?")[0].partition("#")[0].lower().endswith(".pdf") for url in urls),
        })
    return hits
