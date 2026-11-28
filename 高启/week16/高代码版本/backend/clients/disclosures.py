"""按月份查询沪港交易所公开的上市公司公告。"""

import json
from calendar import monthrange
from html import unescape
from urllib.parse import urljoin

import httpx

from ..data_models import SearchHit
from ..enums import Topic
from ..errors import SourceRejected

SSE = "https://www.sse.com.cn/"
SSE_QUERY = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
HKEX = "https://www1.hkexnews.hk/"
HKEX_QUERY = urljoin(HKEX, "search/titleSearchServlet.do")
# 港交所公开查询使用内部 stockId，返回结果仍按证券代码核对。
HKEX_SECURITIES = (
    (Topic.COMPANY, "01088", 9124),  # 中国神华
    (Topic.PEERS, "01898", 13272),   # 中煤能源
    (Topic.PEERS, "01171", 2616),    # 兖矿能源
    (Topic.PEERS, "00902", 2131),    # 华能国际
)


def _month_bounds(month: str) -> tuple[str, str]:
    year, number = map(int, month.split("-"))
    return f"{month}-01", f"{month}-{monthrange(year, number)[1]:02d}"


class DisclosureClient:
    """公告列表只提供待核验线索，正文由网页客户端单独下载。"""

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def _get(self, url: str, params: dict[str, str], referer: str) -> object:
        try:
            response = self._http.get(url, params=params, headers={"Referer": referer}, follow_redirects=False)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            raise SourceRejected(f"公告列表 HTTP {error.response.status_code}") from error
        except httpx.RequestError as error:
            raise SourceRejected("公告列表无法访问") from error
        except ValueError as error:
            raise SourceRejected("公告列表返回的不是有效 JSON") from error

    def sse(self, month: str) -> list[SearchHit]:
        start, end = _month_bounds(month)
        payload = self._get(SSE_QUERY, {
            "productId": "601088", "isPagination": "true", "pageHelp.pageSize": "30",
            "beginDate": start, "endDate": end, "securityType": "0101,120100,020100,020200,120200",
        }, SSE)
        page = payload.get("pageHelp") if isinstance(payload, dict) else None
        rows = page.get("data") if isinstance(page, dict) else None
        if not isinstance(rows, list):
            raise SourceRejected("上交所公告列表结构无法识别")
        return [
            SearchHit(Topic.COMPANY, unescape(row["TITLE"]), urljoin(SSE, row["URL"]), "", "sse")
            for row in rows
            if isinstance(row, dict)
            and row.get("SECURITY_CODE") == "601088"
            and str(row.get("SSEDATE", "")).startswith(f"{month}-")
            and isinstance(row.get("TITLE"), str) and row["TITLE"].strip()
            and isinstance(row.get("URL"), str) and row["URL"].strip()
        ]

    def hkex(self, month: str, topic: Topic, code: str, stock_id: int) -> list[SearchHit]:
        start, end = _month_bounds(month)
        payload = self._get(HKEX_QUERY, {
            "sortDir": "0", "sortByOptions": "DateTime", "category": "0", "market": "SEHK",
            "stockId": str(stock_id), "documentType": "", "fromDate": start.replace("-", ""),
            "toDate": end.replace("-", ""), "title": "", "searchType": "1", "t1code": "",
            "t2Gcode": "", "t2code": "", "lang": "EN",
        }, HKEX)
        rows = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(rows, str):
            try:
                rows = json.loads(rows)
            except ValueError as error:
                raise SourceRejected("港交所公告列表结构无法识别") from error
        if not isinstance(rows, list):
            raise SourceRejected("港交所公告列表结构无法识别")
        year, number = month.split("-")
        return [
            SearchHit(topic, unescape(row["TITLE"]), urljoin(HKEX, row["FILE_LINK"]), "", "hkex")
            for row in rows
            if isinstance(row, dict)
            and row.get("STOCK_CODE") == code
            and str(row.get("DATE_TIME", ""))[2:10] == f"/{number}/{year}"
            and isinstance(row.get("TITLE"), str) and row["TITLE"].strip()
            and isinstance(row.get("FILE_LINK"), str) and row["FILE_LINK"].strip()
        ]
