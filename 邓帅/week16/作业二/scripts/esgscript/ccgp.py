"""检索（二）：直连中国政府采购网搜索接口。

智能体手里的读页工具打不开它（链接带中文编码参数时被拒），所以这是只有脚本能用的数据入口。
"""

import re
import time
from datetime import date
from typing import Any

import httpx
from bs4 import BeautifulSoup

from . import config
from .parsing import PROVINCES

SEARCH_URL = "http://search.ccgp.gov.cn/bxsearch"
SOURCE_SITE = "中国政府采购网"
PAGE_SIZE = 14
"""搜索结果每页的条数：不满一页就说明到底了。"""

_HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
"""要带全浏览器式的 Accept 头：只带 User-Agent 时接口返回一个没有结果的空壳页（2026-11-26 实测）。"""

_NOTICE_LABEL = re.compile(
    r"(中标公告|成交公告|招标公告|更正公告|废标公告|终止公告|竞争性磋商公告|竞争性谈判公告|询价公告|单一来源公示)"
)
_META_DATE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")


def parse_results(html: str) -> list[dict[str, Any]]:
    """解析搜索结果页：每条取标题、地址、摘要、发布日期、采购人、公告类型、省份。"""
    hits: list[dict[str, Any]] = []
    for item in BeautifulSoup(html, "lxml").select("ul.vT-srch-result-list-bid li"):
        anchor = item.find("a", href=True)
        if anchor is None:
            continue
        meta = re.sub(r"\s+", " ", item.get_text(" ", strip=True))
        found = _META_DATE.search(meta)
        label = _NOTICE_LABEL.search(meta)
        purchaser = re.search(r"采购人[:：]\s*([^|]+)", meta)
        remainder = meta[label.end() :] if label else ""
        province = next((name for name in PROVINCES if name in remainder), None)
        paragraph = item.find("p")
        hits.append(
            {
                "url": str(anchor["href"]).strip(),
                "title": anchor.get_text(strip=True),
                "snippet": (paragraph.get_text(" ", strip=True) if paragraph else "")[:300],
                "engine_date": None,
                "published_at": date(int(found[1]), int(found[2]), int(found[3])).isoformat()
                if found
                else None,
                "purchaser": purchaser[1].strip() if purchaser else None,
                "notice_label": label[1] if label else None,
                "region": province,
            }
        )
    return [hit for hit in hits if hit["url"].startswith(("http://", "https://"))]


def yearly_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """把时间窗等分成每段不超过 365 天的几段：接口不认超过一年的区间（只返回空页）。"""
    total = end.toordinal() - start.toordinal() + 1
    count = -(-total // 365)
    first = start.toordinal()
    return [
        (
            date.fromordinal(first + index * total // count),
            date.fromordinal(first + (index + 1) * total // count - 1),
        )
        for index in range(count)
    ]


def search_ccgp(
    keyword: str, start: date, end: date, *, max_pages: int = 5, timeout: float = 15.0
) -> list[dict[str, Any]]:
    """按关键词与日期区间检索，逐页取到不满一页为止。``start`` 到 ``end`` 不得超过一年。"""
    params = {
        "searchtype": "1",
        "bidSort": "0",
        "dbselect": "bidx",
        "kw": keyword,
        "start_time": f"{start:%Y:%m:%d}",
        "end_time": f"{end:%Y:%m:%d}",
        "timeType": "6",
        "bidType": "0",
        "pinMu": "0",
        "pppStatus": "0",
    }
    hits: list[dict[str, Any]] = []
    with httpx.Client(timeout=timeout, headers=_HEADERS, follow_redirects=True) as client:
        for page in range(1, max_pages + 1):
            response = client.get(SEARCH_URL, params=params | {"page_index": str(page)})
            response.raise_for_status()
            found = parse_results(response.content.decode("utf-8", "replace"))
            hits.extend(found)
            if len(found) < PAGE_SIZE:
                break
            time.sleep(0.5)
    return hits
