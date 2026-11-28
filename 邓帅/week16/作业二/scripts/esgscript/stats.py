"""统计：只在样本（范围内的中标公告）上做。数字都出自 data.json，报告里不另算一套。"""

from collections import Counter, defaultdict
from statistics import median
from typing import Any

WAN = 10**4
"""万元的元数。"""

_TYPICAL_COUNT = 8
"""典型项目最多列几条。"""


def format_amount(yuan: float | None) -> str:
    """金额（元）的展示写法：够亿用亿、够万用万，取不到写「金额不可得」。"""
    if yuan is None:
        return "金额不可得"
    if yuan >= 10**8:
        return f"{yuan / 10**8:.2f} 亿元"
    if yuan >= WAN:
        return f"{yuan / WAN:g} 万元"
    return f"{yuan:g} 元"


def amount_bucket(amount: float) -> str:
    if amount < 100 * WAN:
        return "100 万元以下"
    if amount < 1000 * WAN:
        return "100 万（含）至 1000 万元"
    return "1000 万元（含）以上"


def period_of(published: object, quarterly: bool) -> str | None:
    """发布日期归到月（2026-03）或季（2026Q1）；没有日期返回 None。"""
    if not isinstance(published, str) or len(published) < 7:
        return None
    try:
        year, month = int(published[:4]), int(published[5:7])
    except ValueError:
        return None
    return f"{year}Q{(month - 1) // 3 + 1}" if quarterly else published[:7]


def bid_stats(records: list[dict[str, Any]], *, quarterly: bool = True) -> dict[str, Any]:
    """两年汇总的各项分析：热点主题排行、金额分布、月度趋势、采购人类型与地区分布、典型项目。"""
    active = [record for record in records if record.get("verification") != "excluded"]
    sample = [record for record in active if record.get("in_scope") and record.get("notice_type") == "award"]
    with_amount = [record for record in sample if record.get("amount") is not None]
    amounts = [float(record["amount"]) for record in with_amount]

    topic_amount: dict[str, float] = defaultdict(float)
    topic_covered: Counter[str] = Counter()
    period_amount: dict[str, float] = defaultdict(float)
    for record in with_amount:
        topic_amount[record.get("topic") or "未标注"] += float(record["amount"])
        topic_covered[record.get("topic") or "未标注"] += 1
        if period := period_of(record.get("published_at"), quarterly):
            period_amount[period] += float(record["amount"])

    topic_count: Counter[str] = Counter(record.get("topic") or "未标注" for record in sample)
    buckets: Counter[str] = Counter(amount_bucket(amount) for amount in amounts)
    buckets["金额不可得"] = len(sample) - len(amounts)
    period_count: Counter[str] = Counter(
        period for record in sample if (period := period_of(record.get("published_at"), quarterly))
    )

    typical = sorted(with_amount, key=lambda record: float(record["amount"]), reverse=True)
    typical += [record for record in sample if record.get("amount") is None and record not in typical]
    typical = typical[:_TYPICAL_COUNT]

    return {
        "sample_size": len(sample),
        "in_scope_tender_count": sum(
            1 for record in active if record.get("in_scope") and record["notice_type"] == "tender"
        ),
        "out_of_scope_total": sum(1 for record in records if not record.get("in_scope")),
        "excluded_total": len(records) - len(active),
        "summary_only": sum(1 for record in sample if record.get("verification") == "summary-only"),
        "amount_available": len(amounts),
        "amount_rate": len(amounts) / len(sample) if sample else None,
        "amount_median": median(amounts) if amounts else None,
        "amount_max": max(amounts) if amounts else None,
        "amount_total": sum(amounts),
        "topic_rank": [
            {
                "topic": topic,
                "count": count,
                "amount_sum": topic_amount[topic],
                "amount_covered": topic_covered[topic],
            }
            for topic, count in topic_count.most_common()
        ],
        "amount_distribution": [
            {"bucket": name, "count": buckets[name]}
            for name in ("100 万元以下", "100 万（含）至 1000 万元", "1000 万元（含）以上", "金额不可得")
        ],
        "trend": [
            {"period": period, "count": period_count[period], "amount_sum": period_amount[period]}
            for period in sorted(period_count)
        ],
        "purchaser_types": dict(
            Counter(record.get("purchaser_type") or "其它" for record in sample).most_common()
        ),
        "regions": dict(Counter(record.get("region") or "未标注" for record in sample).most_common()),
        "source_sites": dict(
            Counter(record.get("source_site") or "未标注" for record in sample).most_common()
        ),
        "typical": [
            {
                key: record.get(key)
                for key in (
                    "title",
                    "purchaser",
                    "region",
                    "topic",
                    "amount",
                    "amount_text",
                    "winner",
                    "url",
                    "published_at",
                )
            }
            for record in typical
        ],
    }


def monthly_stats(evidence: list[dict[str, Any]], window_start: str, window_end: str) -> dict[str, Any]:
    """月报的来源构成：各章节数、核实状态与可信度分布、日期落窗。"""
    active = [record for record in evidence if record["verification"] != "excluded"]
    in_window = sum(
        1
        for record in active
        if record["published_at"] and window_start <= record["published_at"] <= window_end
    )
    unknown = sum(1 for record in active if not record["published_at"])
    qualified = sum(1 for record in active if record["credibility_tier"] <= 2)
    return {
        "evidence_total": len(evidence),
        "sections": dict(Counter(record["section"] for record in evidence).most_common()),
        "verification": dict(Counter(record["verification"] for record in evidence).most_common()),
        "tiers": dict(Counter(record["credibility_tier"] for record in evidence).most_common()),
        "qualified_sources": qualified,
        "in_window": in_window,
        "unknown_date": unknown,
        "date_in_window_rate": in_window / len(active) if active else None,
    }
