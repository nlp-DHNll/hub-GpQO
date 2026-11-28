"""查询矩阵：月报是「三大部分 × E/S/G × 中英文」，招投标是「主题词 × 公告类型 × 时间段」。

检索词是写死的模板，保证同样的参数得到同样的检索词；预算从上限截断，排在后面的先舍。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from .ccgp import search_ccgp, yearly_chunks
from .zhipu import ZhipuSearch

MONTHLY_PARTS = ("政策/评级/标准动态", "行业新闻与最佳实践", "客户公司动态")
"""月报查询矩阵的三个大部分。"""

ENGLISH_NAMES = {"中国神华": "China Shenhua"}
"""客户的中英文名对照；表里没有的，英文检索词直接用中文名。"""

INDUSTRY_EN = {"煤炭·能源": "coal"}

PEERS = {"煤炭·能源": ("中煤能源", "陕西煤业", "兖矿能源")}
"""对标企业：同行业、规模相当、ESG 披露完善。表里没有的行业由请求给出。"""

_MATRIX: dict[tuple[str, str], tuple[str, str]] = {
    ("政策/评级/标准动态", "E"): (
        "{industry} 碳排放 环保 政策 新规",
        "China {industry_en} carbon emissions environmental regulation",
    ),
    ("政策/评级/标准动态", "S"): (
        "{industry} 安全生产 员工 政策",
        "China {industry_en} safety production worker policy",
    ),
    ("政策/评级/标准动态", "G"): (
        "{client} ESG 披露 治理 监管 准则",
        "{client_en} ESG disclosure governance regulation",
    ),
    ("行业新闻与最佳实践", "E"): (
        "{industry} 碳中和 节能降碳 最佳实践",
        "{industry_en} industry decarbonization best practices",
    ),
    ("行业新闻与最佳实践", "S"): (
        "{industry} 安全生产 社会责任 最佳实践",
        "{industry_en} industry social responsibility best practices",
    ),
    ("行业新闻与最佳实践", "G"): (
        "{industry} ESG 治理 供应链 反腐败",
        "{industry_en} industry ESG governance supply chain",
    ),
    ("客户公司动态", "E"): ("{client} 碳排放 环保 绿色", "{client_en} carbon emissions environmental"),
    ("客户公司动态", "S"): ("{client} 安全生产 员工 社区", "{client_en} safety employees community"),
    ("客户公司动态", "G"): ("{client} ESG 治理 合规 公告", "{client_en} ESG rating governance"),
}
"""月报的 18 格：每格一句中文、一句英文。"""

_BID_PHRASES: dict[str, tuple[str, str]] = {
    "咨询规划": ("双碳规划 咨询服务", "碳达峰 碳中和 路径研究"),
    "碳排放核算与核查": ("碳排放核算 核查服务", "温室气体 核查 服务"),
    "报告编制与鉴证": ("ESG报告 编制 鉴证服务", "可持续发展报告 编制服务"),
    "碳资产管理与交易": ("碳资产管理 开发服务", "碳交易 碳配额 服务"),
    "双碳平台与监测系统": ("双碳 能碳管理平台 建设", "碳排放监测系统 服务"),
    "培训认证": ("碳排放管理员 培训服务", "双碳 培训 认证服务"),
}
"""六类主题各两组检索词。"""

_BID_SYNONYMS = (
    "ESG报告 鉴证 中标公告",
    "可持续发展报告 编制 采购 中标公告",
    "碳核查 服务 成交公告",
    "碳中和 咨询 采购 中标公告",
)
_BID_SITE_LIMITED = (
    "碳排放核算 中标公告",
    "ESG 报告 编制 中标公告",
    "碳资产 管理服务 中标公告",
    "双碳 培训 中标公告",
)
_MONITOR_SYNONYMS = ("ESG 报告 编制 采购公告", "碳核查 服务 采购公告", "碳资产管理 服务 采购公告")
_MONITOR_SITE_LIMITED = ("碳排放核算 招标公告", "ESG报告 采购公告", "双碳 培训 采购公告")

CCGP_KEYWORDS = {
    "summary": (
        "碳排放核算",
        "碳核查",
        "ESG报告",
        "可持续发展报告",
        "碳资产",
        "双碳规划",
        "碳中和咨询",
        "碳管理平台",
        "碳排放培训",
    ),
    "monitor": ("碳排放", "ESG", "碳资产", "碳核查", "双碳", "碳中和"),
}
"""政采网直连用的关键词：它的搜索是按词匹配，词太长搜不到。"""

_GOVERNMENT_SITE = "ccgp.gov.cn"


@dataclass(frozen=True)
class SearchTask:
    """一路检索：``run`` 返回命中列表，``key`` 是缓存键，``label`` 说明它属于矩阵的哪一格。"""

    key: str
    label: str
    backend: str
    text: str
    run: Callable[[], list[dict[str, Any]]]


def _zhipu_task(zhipu: ZhipuSearch, label: str, text: str, options: dict[str, Any]) -> SearchTask:
    return SearchTask(
        key=f"zhipu|{text}|{sorted(options.items())}",
        label=label,
        backend="zhipu",
        text=text,
        run=lambda: zhipu.search(
            text,
            recency=str(options.get("recency", "noLimit")),
            location=str(options.get("location", "cn")),
            domain=options.get("domain"),
        ),
    )


def _zhipu_tasks(zhipu: ZhipuSearch, items: list[tuple[str, str, dict[str, Any]]]) -> list[SearchTask]:
    return [_zhipu_task(zhipu, label, text, options) for label, text, options in items]


def monthly_tasks(spec: Any, zhipu: ZhipuSearch) -> list[SearchTask]:
    """月报：18 格矩阵排最前，其后依次是对标企业的披露、评级与补搜，到预算为止。"""
    names = {
        "client": spec.client or "",
        "industry": spec.industry or "",
        "client_en": spec.client_en or ENGLISH_NAMES.get(spec.client or "", spec.client or ""),
        "industry_en": spec.industry_en or INDUSTRY_EN.get(spec.industry or "", spec.industry or ""),
    }
    items: list[tuple[str, str, dict[str, Any]]] = []
    for (part, letter), (chinese, english) in _MATRIX.items():
        items.append(
            (f"{part}·{letter}·中文", chinese.format(**names), {"recency": "oneMonth", "location": "cn"})
        )
        items.append(
            (f"{part}·{letter}·英文", english.format(**names), {"recency": "oneMonth", "location": "us"})
        )
    for peer in spec.peers:
        items.append(
            (
                f"对标企业·{peer}",
                f"{peer} ESG 可持续发展报告 碳排放",
                {"recency": "oneYear", "location": "cn"},
            )
        )
    items.append(
        (
            "政策/评级/标准动态·评级·补搜",
            f"{names['client']} MSCI ESG 评级",
            {"recency": "oneMonth", "location": "cn"},
        )
    )
    items.append(
        (
            "政策/评级/标准动态·评级·补搜",
            f"{names['client_en']} ESG rating MSCI Sustainalytics",
            {"recency": "oneYear", "location": "us"},
        )
    )
    items.append(
        ("客户公司动态·补搜", f"{names['client']} 可持续发展 公告", {"recency": "oneMonth", "location": "cn"})
    )
    items.append(
        (
            "行业新闻与最佳实践·补搜",
            f"{names['industry']} 低碳转型 动态",
            {"recency": "oneMonth", "location": "cn"},
        )
    )
    return _zhipu_tasks(zhipu, items[: spec.budget])


def bid_tasks(spec: Any, zhipu: ZhipuSearch) -> list[SearchTask]:
    """招投标：六类主题 × 中标公告 × 两轮时间段打头，其后是同义写法与站点限定。"""
    items: list[tuple[str, str, dict[str, Any]]] = []
    if spec.mode == "monitor":
        for topic, phrases in _BID_PHRASES.items():
            items.append(
                (f"监控·{topic}", f"{phrases[0]} 招标公告", {"recency": "oneWeek", "location": "cn"})
            )
        for index, text in enumerate(_MONITOR_SYNONYMS):
            items.append((f"监控·同义写法{index + 1}", text, {"recency": "oneWeek", "location": "cn"}))
        for index, text in enumerate(_MONITOR_SITE_LIMITED):
            items.append(
                (
                    f"监控·政采网限定{index + 1}",
                    text,
                    {"recency": "oneMonth", "location": "cn", "domain": _GOVERNMENT_SITE},
                )
            )
        return _zhipu_tasks(zhipu, items[: spec.budget])
    for topic, phrases in _BID_PHRASES.items():
        items.append(
            (f"汇总·{topic}·近一年", f"{phrases[0]} 中标公告", {"recency": "oneYear", "location": "cn"})
        )
        items.append(
            (f"汇总·{topic}·不限", f"{phrases[1]} 中标公告", {"recency": "noLimit", "location": "cn"})
        )
    for topic, phrases in _BID_PHRASES.items():
        items.append(
            (f"汇总·{topic}·近一年·换词", f"{phrases[1]} 中标公告", {"recency": "oneYear", "location": "cn"})
        )
    for recency in ("noLimit", "oneYear"):
        for index, text in enumerate(_BID_SYNONYMS):
            items.append((f"汇总·同义写法{index + 1}", text, {"recency": recency, "location": "cn"}))
        for index, text in enumerate(_BID_SITE_LIMITED):
            items.append(
                (
                    f"汇总·政采网限定{index + 1}",
                    text,
                    {"recency": recency, "location": "cn", "domain": _GOVERNMENT_SITE},
                )
            )
    for topic, phrases in _BID_PHRASES.items():
        items.append(
            (f"汇总·{topic}·招标公告", f"{phrases[0]} 招标公告", {"recency": "oneYear", "location": "cn"})
        )
    for topic, _ in _BID_PHRASES.items():
        items.append(
            (
                f"汇总·{topic}·英文",
                f"China {topic} service tender award",
                {"recency": "noLimit", "location": "us"},
            )
        )
    return _zhipu_tasks(zhipu, items[: spec.budget])


def _ccgp_task(keyword: str, start: date, end: date) -> SearchTask:
    return SearchTask(
        key=f"ccgp|{keyword}|{start}|{end}",
        label=f"政采网直连·{keyword}",
        backend="ccgp",
        text=keyword,
        run=lambda: search_ccgp(keyword, start, end),
    )


def ccgp_tasks(spec: Any) -> list[SearchTask]:
    """政采网直连：每个关键词按时间窗检索，窗口超过一年就按年分段。监控模式从基线日的下一天开始。"""
    start = (
        spec.window_start if spec.mode == "summary" else date.fromordinal(spec.window_start.toordinal() + 1)
    )
    return [
        _ccgp_task(keyword, first, last)
        for keyword in CCGP_KEYWORDS[spec.mode]
        for first, last in yearly_chunks(start, spec.window_end)
    ]


def build_tasks(spec: Any, zhipu: ZhipuSearch) -> list[SearchTask]:
    """一次运行的全部检索任务：智谱搜索受预算约束，政采网直连另计。"""
    tasks = monthly_tasks(spec, zhipu) if spec.case == "monthly-report" else bid_tasks(spec, zhipu)
    if spec.case == "bid-radar" and spec.ccgp:
        tasks += ccgp_tasks(spec)
    return tasks
