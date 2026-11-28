"""通过 DDGS 查找候选网页，并将搜索结果转换成 Agent 的线索。"""

from collections.abc import Callable
from html import unescape
from time import sleep

from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException

from ..data_models import SearchHit
from ..enums import Topic
from ..errors import RunFailure


class DDGSSearchClient:
    """网页检索客户端，网络失败时最多再试一次。"""

    def __init__(self) -> None:
        self._engine = DDGS(timeout=8)

    def search(
        self,
        query: str,
        topic: Topic,
        *,
        on_retry: Callable[[str], object] | None = None,
    ) -> list[SearchHit]:
        for attempt in (1, 2):
            try:
                results = self._engine.text(query, region="cn-zh", max_results=8)
            except RatelimitException as error:
                raise RunFailure("DDGS 网页搜索受限，请稍后重试") from error
            except DDGSException as error:
                # DDGS 用这个异常表示查询成功但没有结果。
                if str(error).strip().rstrip(".").casefold() == "no results found":
                    return []
                if attempt == 2:
                    raise RunFailure("DDGS 网页搜索失败，请检查网络后重试") from error
                if on_retry is not None:
                    on_retry("DDGS 搜索请求失败")
                sleep(1)
            else:
                return self._to_hits(results, topic)
        raise AssertionError("搜索应在两次尝试内返回或失败")

    @staticmethod
    def _to_hits(results: list[dict[str, str]], topic: Topic) -> list[SearchHit]:
        hits = []
        for item in results:
            if not isinstance(item, dict):
                continue
            title, url, snippet = (item.get(key, "") for key in ("title", "href", "body"))
            if isinstance(title, str) and isinstance(url, str) and title.strip() and url.strip():
                body = unescape(snippet) if isinstance(snippet, str) else ""
                hits.append(SearchHit(topic, unescape(title).strip(), url.strip(), body))
        return hits
