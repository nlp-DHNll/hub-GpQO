"""ResearchState:研究循环的共享状态,同时是过程记录(process.json)的数据源。

reducer 约定(LangGraph 节点返回增量自动合并):
- rounds / findings:追加(operator.add)
- sources / seen_urls:dict 合并(新键加入、同键覆盖)
- search_count:累加(operator.add)
- degraded:布尔或(一旦降级永置位)
- 其余字段:后写覆盖
"""
import operator
from typing import Annotated, TypedDict


def merge_dict(old: dict | None, new: dict | None) -> dict:
    return {**(old or {}), **(new or {})}


def merge_true(old: bool | None, new: bool | None) -> bool:
    return bool(old) or bool(new)


class SourceMeta(TypedDict, total=False):
    """来源元数据(url 即外层 dict 的 key)。"""

    title: str
    summary: str
    date_published: str
    from_summary: bool  # 摘要兜底(正文抓取失败)
    cited: int          # 报告中被 [n] 引用次数


class RoundRecord(TypedDict, total=False):
    """一轮研究的完整记录(search 建骨架、read/reflect 补齐、reflect 落入 rounds)。"""

    round: int
    queries: list[str]
    failed_queries: list[str]
    results: list[dict]  # 本轮去重后的新搜索结果
    read_urls: list[str]
    findings_added: int
    gaps: str


class ResearchState(TypedDict, total=False):
    task_id: str
    topic: str
    plan: list[str]  # 子问题
    rounds: Annotated[list[RoundRecord], operator.add]
    current_round: RoundRecord  # 本轮中间态(覆盖写)
    sources: Annotated[dict[str, SourceMeta], merge_dict]
    findings: Annotated[list[dict], operator.add]  # {point, quote, url, from_summary}
    seen_urls: Annotated[dict[str, bool], merge_dict]  # 跨轮 URL 去重
    iteration: int
    pending_queries: list[str]
    sufficient: bool
    degraded: Annotated[bool, merge_true]  # 节点异常降级标记
    report_md: str
    search_count: Annotated[int, operator.add]


def initial_state(task_id: str, topic: str) -> ResearchState:
    return {
        "task_id": task_id,
        "topic": topic,
        "plan": [],
        "rounds": [],
        "current_round": {},
        "sources": {},
        "findings": [],
        "seen_urls": {},
        "iteration": 0,
        "pending_queries": [],
        "sufficient": False,
        "degraded": False,
        "report_md": "",
        "search_count": 0,
    }
