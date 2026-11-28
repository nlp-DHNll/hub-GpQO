"""从受支持的公开站点下载候选原文。"""

from urllib.parse import urljoin, urlsplit

import httpx

from ..data_models import SourcePage
from ..errors import SourceRejected

PRIMARY_SITES = {
    "csec.com": "中国神华",
    "shenhuachina.com": "中国神华",
    "ceic.com": "国家能源集团",
    "chinacoalenergy.com": "中煤能源",
    "yanzhoucoal.com.cn": "兖矿能源",
    "hpi.com.cn": "华能国际",
    "sse.com.cn": "上海证券交易所",
    "hkexnews.hk": "香港交易所披露易",
    "cninfo.com.cn": "巨潮资讯",
    "mee.gov.cn": "生态环境部",
    "nea.gov.cn": "国家能源局",
    "ndrc.gov.cn": "国家发展改革委",
    "mof.gov.cn": "财政部",
    "samr.gov.cn": "市场监管总局",
    "csrc.gov.cn": "中国证监会",
    "www.gov.cn": "中国政府网",
    "ifrs.org": "IFRS 基金会",
    "globalreporting.org": "全球报告倡议组织",
}
NEWS_SITES = {
    "news.cn": "新华网",
    "xinhuanet.com": "新华网",
    "ce.cn": "中国经济网",
    "chinanews.com.cn": "中国新闻网",
    "cnenergynews.cn": "中国能源报",
}
MAX_BYTES = 5 * 1024 * 1024
REDIRECT_STATUS = {301, 302, 303, 307, 308}


def publisher_site(url: str) -> tuple[str, bool] | None:
    """返回支持站点的发布者和是否为优先来源。"""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        ports = {"https": 443, "http": 80}
        if (
            parts.scheme not in ports
            or parts.username is not None
            or parts.port not in (None, ports[parts.scheme])
            or "\\" in url
        ):
            return None
    except ValueError:
        return None
    for sites, primary in ((PRIMARY_SITES, True), (NEWS_SITES, False)):
        for domain, name in sites.items():
            if host == domain or host.endswith(f".{domain}"):
                return name, primary
    return None


class SourcePageClient:
    """限制下载范围、重定向和大小，获取 HTML 网页原文。"""

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def fetch(self, url: str) -> SourcePage:
        for _ in range(4):
            if publisher_site(url) is None:
                raise SourceRejected("站点未收录")
            if urlsplit(url).path.lower().endswith(".pdf"):
                raise SourceRejected("候选链接不是网页")
            try:
                with self._http.stream("GET", url, follow_redirects=False) as response:
                    if response.status_code in REDIRECT_STATUS:
                        location = response.headers.get("location")
                        if not location:
                            raise SourceRejected("原文重定向无目标")
                        url = urljoin(str(response.url), location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").partition(";")[0].strip().lower()
                    if content_type not in {"text/html", "application/xhtml+xml"}:
                        raise SourceRejected("原文不是 HTML 网页")
                    body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=64 * 1024):
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise SourceRejected("原文超过下载限制")
                    return SourcePage(
                        url=str(response.url),
                        body=bytes(body),
                        encoding=response.charset_encoding,
                    )
            except httpx.HTTPStatusError as error:
                raise SourceRejected(f"原文 HTTP {error.response.status_code}") from error
            except (httpx.RequestError, httpx.InvalidURL) as error:
                raise SourceRejected("原文无法访问") from error
        raise SourceRejected("原文重定向次数过多")
