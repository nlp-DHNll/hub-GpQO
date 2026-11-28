"""核验原文的发布日期和正文，合并重复来源。"""

import json
import re
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..clients.source_pages import SourcePageClient, publisher_site
from ..data_models import SearchHit, Source, SourcePage
from ..errors import SourceRejected
from ..log.run_logger import RunLogger

DATE = re.compile(r"(\d{4})\s*[-./年]\s*(\d{1,2})\s*[-./月]\s*(\d{1,2})(?!\d)")
PUBLISHED = re.compile(
    r"(?:发布日期|发布时间|发稿时间|发布于|发表时间|刊发日期|published(?:\s+on)?|publication date)"
    r"\s*[:：]?\s*",
    re.IGNORECASE,
)
DATE_META = {"article:published_time", "datepublished", "pubdate", "publishdate", "publish_time"}
BODY_SELECTORS = (
    "[itemprop=articleBody]",
    "article",
    "#UCAP-CONTENT",
    ".TRS_Editor",
    "#zoom",
    "#articleContent",
    ".article-content",
    "main",
)
MAX_EXCERPT = 800


def _text(value: str) -> str:
    return " ".join(value.split())


def _date(value: str) -> date | None:
    match = DATE.match(value.strip())
    if match is not None:
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            pass
    return None


def _published_date(metadata: list[str], visible_text: str) -> date:
    dates = {parsed for value in metadata if (parsed := _date(value)) is not None}
    if not dates:
        dates = {
            parsed
            for label in PUBLISHED.finditer(visible_text)
            if (parsed := _date(visible_text[label.end():label.end() + 40])) is not None
        }
    if len(dates) != 1:
        raise SourceRejected("原文发布日期无法确认")
    return dates.pop()


def _jsonld_dates(soup: BeautifulSoup) -> list[str]:
    values = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or script.get_text())
        except (ValueError, RecursionError):
            continue
        nodes = list(payload) if isinstance(payload, list) else [payload]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph")
            if isinstance(graph, list):
                nodes.extend(graph)
            if isinstance(value := node.get("datePublished"), str):
                values.append(value)
    return values


def _html_article(page: SourcePage) -> tuple[str, str, date, str]:
    soup = BeautifulSoup(page.body, "html.parser", from_encoding=page.encoding)
    meta: dict[str, str] = {}
    dates = _jsonld_dates(soup)
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name") or tag.get("itemprop")
        value = tag.get("content")
        if isinstance(key, str) and isinstance(value, str):
            meta.setdefault(key.casefold(), _text(value))
            if key.casefold() in DATE_META:
                dates.append(value)
    for tag in soup.select("time[itemprop=datePublished][datetime]"):
        if isinstance(value := tag.get("datetime"), str):
            dates.append(value)
    for tag in soup.select("script, style, nav, footer, aside"):
        tag.decompose()
    container = next(
        (node for selector in BODY_SELECTORS if (node := soup.select_one(selector)) is not None),
        None,
    )
    paragraphs = (container or soup).find_all("p")
    article = " ".join(text for p in paragraphs if len(text := _text(p.get_text(" "))) >= 20)
    if not article and container is not None:
        article = _text(container.get_text(" "))
    published = _published_date(dates, _text(soup.get_text(" "))[:2500])
    heading = soup.find("h1") or soup.title
    title = meta.get("og:title") or (_text(heading.get_text(" ")) if heading else "")
    publisher = meta.get("contentsource") or meta.get("og:site_name") or meta.get("sitename") or ""
    return title, publisher, published, article


def _canonical(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(query), ""))


def _rank(url: str) -> int:
    site = publisher_site(url)
    return 0 if site and site[1] else 1


def _source(hit: SearchHit, page: SourcePage, month: str) -> Source:
    site = publisher_site(page.url)
    if site is None:
        raise SourceRejected("站点未收录")
    title, publisher, published, article = _html_article(page)
    if published.isoformat()[:7] != month:
        raise SourceRejected("原文发布日期不在目标月")
    if len(article) < 60:
        raise SourceRejected("原文正文不足")
    return Source(
        "", (hit.topic,), title or hit.title, publisher or site[0],
        published, _canonical(page.url), article[:MAX_EXCERPT],
    )


def _title_key(title: str) -> str:
    return re.sub(r"[^\w]+", "", title.casefold())


def _merge(sources: list[Source], candidate: Source) -> None:
    """同一资料保留编号并合并主题，优先采用原始发布站点。"""
    for index, prior in enumerate(sources):
        same_title = (
            prior.published_on == candidate.published_on
            and _title_key(prior.title) == _title_key(candidate.title)
        )
        if prior.url == candidate.url or same_title:
            topics = tuple(dict.fromkeys((*prior.topics, *candidate.topics)))
            preferred = candidate if _rank(candidate.url) < _rank(prior.url) else prior
            sources[index] = replace(preferred, source_id=prior.source_id, topics=topics)
            return
    sources.append(replace(candidate, source_id=f"S{len(sources) + 1:02d}"))


def filter_sources(
    month: str,
    hits: list[SearchHit],
    existing: list[Source],
    logger: RunLogger,
    *,
    client: SourcePageClient,
) -> list[Source]:
    """筛选本轮线索并与已有资料合并，统计各入口核验通过的网页。"""
    sources = list(existing)
    rejected: Counter[str] = Counter()
    rejected_urls: dict[str, str] = {}
    verified: dict[str, set[str]] = defaultdict(set)
    for hit in sorted(hits, key=lambda item: _rank(item.url)):
        if hit.provider:
            verified[hit.provider]
        canonical = hit.url
        try:
            if publisher_site(hit.url) is None:
                raise SourceRejected("站点未收录")
            canonical = _canonical(hit.url)
            if canonical in rejected_urls:
                raise SourceRejected(rejected_urls[canonical])
            known = next((source for source in sources if source.url == canonical), None)
            candidate = (
                replace(known, topics=(hit.topic,))
                if known is not None
                else _source(hit, client.fetch(hit.url), month)
            )
            _merge(sources, candidate)
            if hit.provider:
                verified[hit.provider].add(candidate.url)
        except SourceRejected as error:
            reason = str(error)
            rejected_urls[canonical] = reason
            rejected[reason] += 1
    if rejected:
        logger.record("sources_rejected", details={"counts": dict(rejected)})
    if verified:
        logger.record("source_provider_verified", details={
            "counts": {provider: len(urls) for provider, urls in verified.items()},
        })
    return sources
