"""抓取：取页面正文与发布日期线索。单页失败一律降级并记下原因，不抛异常、不中断整次运行。"""

import re
import time
from typing import Any

import httpx
import trafilatura
from bs4 import BeautifulSoup

from . import config
from .bridge import contract

_HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
"""抓取网页的请求头：不少政府站点对非浏览器标识返回 4xx。"""

_HARD_LIMIT_SECONDS = 20.0
"""一页最多花多久：有的站点慢速吐字节，读超时拦不住，只能自己看表。"""

_MAX_BYTES = 1_500_000
"""一页最多读多少字节；超出就停，正文用已读到的部分。"""

_CHARSET = re.compile(rb"charset=[\"']?([\w-]+)", re.I)
"""从网页前几 KB 里找编码声明：有的站点响应头写的编码不对。"""

_META_TAG = re.compile(
    r"<meta[^>]+(?:property|name|itemprop)=[\"']"
    r"(?:article:published_time|og:release_date|publishdate|pubdate|publish_date|datePublished|PubDate"
    r"|weibo:article:create_at|apub:time|ColumnPubDate|columnpubdate|firstpublishedtime|dcterms.created)"
    r"[\"'][^>]*>",
    re.I,
)
_META_CONTENT = re.compile(r"content=[\"']([^\"']+)[\"']", re.I)
_TEXT_DATE = re.compile(
    r"(?:发布时间|发布日期|发布于|发稿时间|时间|日期)\s*[：:]\s*(\d{4}\s*[年./-]\s*\d{1,2}\s*[月./-]\s*\d{1,2})"
)

Page = dict[str, Any]


def _decode(raw: bytes, declared: str | None) -> str:
    found = _CHARSET.search(raw[:4096])
    encoding = (found[1].decode("ascii", "ignore") if found else None) or declared or "utf-8"
    try:
        return raw.decode(encoding, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


def _plain_text(html: str) -> str:
    """正文提取库认不出版式时的退路：去掉脚本与样式后取全文。"""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    return "\n".join(lines)


def _iso_date(value: str) -> str | None:
    """用契约里的日期解析认一个日期，返回 YYYY-MM-DD；认不出返回 None。"""
    parsed = contract.parse_date(value)
    return parsed.isoformat() if parsed else None


def _published_hint(html: str, text: str) -> str | None:
    """页面上写得明白的发布日期：先看 meta 标签，再看正文开头的「发布时间：…」。认不出返回 None。"""
    for tag in _META_TAG.findall(html):
        content = _META_CONTENT.search(tag)
        if content and (found := _iso_date(content[1])):
            return found
    head = text[:1200]
    if matched := _TEXT_DATE.search(head):
        return _iso_date(matched[1])
    return None


def fetch_page(url: str, *, timeout: float = 8.0, max_chars: int = 6000) -> Page:
    """抓一个页面，返回正文（截到 max_chars）、标题与发布日期线索。失败时 ok 为 False 并带原因。"""
    page: Page = {
        "url": url,
        "ok": False,
        "status": None,
        "final_url": None,
        "title": "",
        "text": "",
        "date_hint": None,
        "error": None,
    }
    started = time.perf_counter()
    try:
        budget = httpx.Timeout(timeout, read=6.0)
        with httpx.Client(timeout=budget, headers=_HEADERS, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                page["status"] = response.status_code
                page["final_url"] = str(response.url)
                if response.status_code >= 400:
                    page["error"] = f"HTTP {response.status_code}"
                    return page
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                if "html" not in content_type and content_type not in ("text/plain", ""):
                    page["error"] = f"不是网页（{content_type}）"
                    return page
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > _MAX_BYTES or time.perf_counter() - started > _HARD_LIMIT_SECONDS:
                        break
        html = _decode(b"".join(chunks), response.encoding)
        title = BeautifulSoup(html, "lxml").title
        page["title"] = title.get_text(strip=True) if title else ""
        text = trafilatura.extract(html, include_comments=False, include_tables=True, favor_recall=True) or ""
        if len(text) < 200:
            text = _plain_text(html)
        page["text"] = text[:max_chars]
        page["date_hint"] = _published_hint(html, text)
        if len(text) < 80:
            page["error"] = "正文过短"
        else:
            page["ok"] = True
    except Exception as exc:  # 超时、连接失败、解码异常都只影响这一页
        page["error"] = type(exc).__name__
    return page


def normalize(text: object) -> str:
    """去掉全部空白，用来判断一段摘录是否逐字出自原文。"""
    return re.sub(r"\s+", "", text) if isinstance(text, str) else ""


def contains(haystack: object, needle: object) -> bool:
    """摘录（去空白后）是否出现在原文里。"""
    return bool(needle) and normalize(needle) in normalize(haystack)
