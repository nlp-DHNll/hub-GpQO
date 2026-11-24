"""受限抓取：只取列表页里的公告链接，不做正文抓取、不绕反爬。

边界（写死在代码里，不靠使用者自觉）
------------------------------------
- 只抓 ``config/sources.yaml`` 里显式配置的 ``list_url``，不跟随站外链接；
- 抓之前查 ``robots.txt``，被禁止就跳过并把原因写进 failures；
- 每个源最多 ``max_pages`` 页，两次请求之间 ``delay`` 秒，不并发；
- 只保留锚文本命中关键词的链接，导航词（首页/登录/更多/下一页）一律丢弃；
- 不解析正文、不执行 JS。JS 渲染的列表页抓回来是空壳，这是**已知限制**，
  这类站点请改用 ``mode: search_site``。

为什么不用无头浏览器：反爬与登录墙面前，无头浏览器的成功率并不比 ``site:``
定向检索高，却会带来浏览器依赖、封 IP 风险和数倍的维护成本。这个 skill 的
定位是「快速拿到可核对的清单」，不是爬虫框架。
"""

from __future__ import annotations

import time
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from . import netguard
from . import search as search_mod

USER_AGENT = (
    "Mozilla/5.0 (compatible; esg-tender-intel/2.0; +public-tender-index)"
)
# 列表页的导航/功能词。命中即丢——它们的锚文本很短、数量大，会灌满 Hit 列表
_NAV_WORDS = (
    "首页", "登录", "注册", "更多", "上一页", "下一页", "返回", "网站地图",
    "无障碍", "简", "繁", "English", "设为首页", "加入收藏", "打印", "关闭",
    "用户中心", "帮助", "关于我们", "联系我们",
)
_SKIP_SUFFIX = (".css", ".js", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".rar", ".pdf")


class CrawlError(RuntimeError):
    """抓取失败（被 robots 禁止、HTTP 错误、页面结构不可用）。"""


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        mapping = dict(attrs)
        self._href = mapping.get("href")
        self._buf = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        text = " ".join("".join(self._buf).split())
        self.links.append((self._href, text))
        self._href = None
        self._buf = []


def extract_links(
    html: str,
    base_url: str,
    keywords: list[str],
    *,
    min_len: int = 8,
    max_len: int = 120,
    limit: int = 200,
) -> list[dict[str, str]]:
    """从列表页 HTML 抽公告链接。纯函数，测试里直接喂字符串。

    ``min_len=8`` 是经验值：中文标题短于 8 字基本是导航（「招标公告」四个字
    的栏目页链接会把整页撑满）。
    """
    parser = _LinkParser()
    try:
        parser.feed(html or "")
    except Exception:  # 畸形 HTML 不该让整轮检索失败
        pass

    base_host = urlparse(base_url).netloc
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, text in parser.links:
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = urljoin(base_url, href.strip())
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.netloc != base_host:
            continue
        if parsed.path.lower().endswith(_SKIP_SUFFIX):
            continue
        url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}" + (
            f"?{parsed.query}" if parsed.query else ""
        )
        if url.rstrip("/") == base_url.rstrip("/") or url in seen:
            continue
        if not (min_len <= len(text) <= max_len):
            continue
        if any(word == text or word in text[:4] for word in _NAV_WORDS):
            continue
        if keywords and not any(word in text for word in keywords):
            continue
        seen.add(url)
        out.append({"title": text, "url": url})
        if len(out) >= limit:
            break
    return out


def fetch_html(url: str, *, timeout: float = 15.0) -> str:
    # 走 netguard：不跟随自动重定向，每一跳都校验公网地址。
    # ``follow_redirects=True`` + 无校验 = 配一个公网域名 302 到 127.0.0.1 即可 SSRF。
    response = netguard.safe_get(
        url,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
    )
    return response.text


def robots_allows(
    url: str, *, fetcher: Callable[[str], str] = fetch_html, agent: str = "esg-tender-intel"
) -> bool:
    """查 robots.txt。取不到（404/超时）按「未声明」放行——这是常见约定。"""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        text = fetcher(robots_url)
    except Exception:
        return True
    if not text or "<html" in text[:200].lower():
        return True
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(agent, url)


def crawl_source(
    source: dict[str, Any],
    *,
    keywords: list[str],
    max_pages: int = 1,
    delay: float = 1.0,
    fetcher: Callable[[str], str] | None = None,
    respect_robots: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> list[search_mod.Hit]:
    """抓一个源的列表页，返回 Hit 列表。

    ``fetcher``/``sleep`` 可注入，测试里不需要真的发请求。分页只在源显式配了
    ``page_param``（如 ``page``）时才跟随，避免按 URL 规律瞎猜、抓到 404 或
    翻出历史全站。
    """
    list_url = str(source.get("list_url") or "").strip()
    if not list_url:
        raise CrawlError(f"源 {source.get('id')} 是 crawl 模式但没配 list_url")
    fetch = fetcher or fetch_html

    hits: list[search_mod.Hit] = []
    pages = max(1, int(source.get("max_pages") or max_pages or 1))
    page_param = str(source.get("page_param") or "").strip()
    if pages > 1 and not page_param:
        pages = 1  # 没给分页参数就不猜，宁可少抓

    for index in range(pages):
        url = list_url
        if index and page_param:
            separator = "&" if "?" in list_url else "?"
            url = f"{list_url}{separator}{page_param}={index + 1}"
        if respect_robots and not robots_allows(url, fetcher=fetch):
            if index == 0:
                raise CrawlError(f"robots.txt 禁止抓取 {url}")
            break
        if index:
            sleep(max(0.0, delay))
        try:
            html = fetch(url)
        except Exception as exc:  # httpx 的异常类型很多，统一降级成 CrawlError
            raise CrawlError(f"抓取 {url} 失败：{type(exc).__name__}") from exc
        for link in extract_links(html, url, keywords):
            hits.append(
                search_mod.Hit(
                    title=link["title"],
                    url=link["url"],
                    snippet="",  # 列表页只有标题，正文要另抓；不编造摘要
                    site=str(source.get("name") or source.get("id") or ""),
                    # 列表页没有可靠的发布日期，留空由上层计入 unknown_date。
                    # 用「今天」顶替会让窗口过滤失效（等于伪造日期）。
                    published="",
                    query=f"crawl:{source.get('id')}",
                    provider="crawl",
                )
            )
    return hits

