"""从监管部门和准则发布机构的公开栏目发现候选原文。"""

from calendar import month_name
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..clients.source_pages import SourcePageClient, publisher_site
from ..data_models import SearchHit
from ..enums import Topic

ENERGY_INDEX = "https://prpq.nea.gov.cn/jieduyuhuiying"
CATALOGS = {
    "nea": (ENERGY_INDEX, (Topic.POLICY, Topic.INDUSTRY), ("煤电", "煤炭", "降碳", "电力")),
    "mee": (
        "https://www.mee.gov.cn/zcwj/zcjd/", (Topic.POLICY,),
        ("生态环境监测", "污染", "碳", "煤电", "煤炭", "环境基准"),
    ),
    "ndrc": (
        "https://www.ndrc.gov.cn/xxgk/jd/jd/wap_index.html", (Topic.POLICY, Topic.INDUSTRY),
        ("煤电", "煤炭", "能源保供", "碳", "节能", "电力", "可再生能源"),
    ),
    "issb": ("https://www.ifrs.org/news-and-events/updates/issb/", (Topic.POLICY,), ()),
}


def catalog_hits(
    provider: str, month: str, topics: tuple[Topic, ...], client: SourcePageClient,
) -> list[SearchHit]:
    index, supported, keywords = CATALOGS[provider]
    matched_topics = [topic for topic in topics if topic in supported]
    if not matched_topics:
        return []

    page = client.fetch(index)
    soup = BeautifulSoup(page.body, "html.parser", from_encoding=page.encoding)
    year, number = month.split("-")
    issb_issue = f"/{year}/issb-update-{month_name[int(number)].lower()}-{year}"
    month_path = f"/{year}{number}"
    candidates: dict[str, str] = {}
    for link in soup.select("a[href]"):
        href = link.get("href")
        title = link.get_text(" ", strip=True)
        if not isinstance(href, str) or not title:
            continue
        url = urljoin(page.url, href)
        if publisher_site(url) != publisher_site(index):
            continue
        path = urlsplit(url).path
        if provider == "issb":
            matches = path.rstrip("/").removesuffix(".html").endswith(issb_issue)
        else:
            matches = month_path in path and any(word in title for word in keywords)
        if matches:
            candidates.setdefault(url, title)
        if len(candidates) == 8:
            break
    return [
        SearchHit(topic, title, url, "", provider)
        for url, title in candidates.items()
        for topic in matched_topics
    ]
