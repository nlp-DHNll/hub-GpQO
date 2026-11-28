#!/usr/bin/env python3
"""
ESG / 双碳招投标聚合分析（确定性统计脚本）。

读取 normalize_bids.py 产出的标准化 JSON，输出：
  概览（样本量、已披露金额合计/均值/中位数/极值）、金额分档分布、
  品类 / 客户类型 / 地区 / 中标方聚合、月度趋势；可同时生成 Markdown 分析骨架。

用法：
  python analyze_bids.py --input normalized.json --out analysis.json \
      --report analysis.md
"""

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime


def agg_by(bids, field):
    groups = defaultdict(list)
    for b in bids:
        groups[b[field]].append(b)
    out = []
    for name, items in groups.items():
        amounts = [x["amount_wan"] for x in items if x["amount_wan"] is not None]
        out.append({
            "name": name,
            "count": len(items),
            "amount_total_wan": round(sum(amounts), 2) if amounts else None,
            "amount_avg_wan": round(statistics.mean(amounts), 2) if amounts else None,
            "max_wan": round(max(amounts), 2) if amounts else None,
        })
    out.sort(key=lambda x: (x["amount_total_wan"] or 0), reverse=True)
    return out


def main():
    ap = argparse.ArgumentParser(description="招投标聚合分析")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True, help="分析结果 JSON 路径")
    ap.add_argument("--report", help="可选：Markdown 分析骨架输出路径")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    bids = data["bids"]

    amounts = [b["amount_wan"] for b in bids if b["amount_wan"] is not None]
    overview = {
        "total": len(bids),
        "priced_count": len(amounts),
        "unpriced_count": len(bids) - len(amounts),
        "amount_total_wan": round(sum(amounts), 2) if amounts else None,
        "amount_avg_wan": round(statistics.mean(amounts), 2) if amounts else None,
        "amount_median_wan": round(statistics.median(amounts), 2) if amounts else None,
        "amount_max_wan": round(max(amounts), 2) if amounts else None,
        "amount_min_wan": round(min(amounts), 2) if amounts else None,
    }

    # 金额分档
    band_order = ["小型(<10万)", "中型(10-30万)", "大型(30-100万)", "重大(≥100万)", "未披露"]
    bands = defaultdict(list)
    for b in bids:
        bands[b["amount_band"]].append(b)
    band_dist = []
    for name in band_order:
        items = bands.get(name, [])
        if not items:
            continue
        amts = [x["amount_wan"] for x in items if x["amount_wan"] is not None]
        band_dist.append({
            "band": name,
            "count": len(items),
            "share": round(len(items) / len(bids), 3) if bids else 0,
            "amount_total_wan": round(sum(amts), 2) if amts else None,
        })

    # 月度趋势
    months = defaultdict(list)
    for b in bids:
        months[b["date"][:7]].append(b)
    trend = []
    for m in sorted(months):
        items = months[m]
        amts = [x["amount_wan"] for x in items if x["amount_wan"] is not None]
        trend.append({
            "month": m,
            "count": len(items),
            "amount_total_wan": round(sum(amts), 2) if amts else None,
        })

    analysis = {
        "meta": {"generated_at": datetime.now().isoformat(timespec="seconds")},
        "overview": overview,
        "amount_band_distribution": band_dist,
        "by_category": agg_by(bids, "category"),
        "by_buyer_type": agg_by(bids, "buyer_type"),
        "by_region": agg_by(bids, "region"),
        "by_winner": agg_by(bids, "winner"),
        "monthly_trend": trend,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    if args.report:
        lines = ["# ESG / 双碳招投标汇总分析（近 2 年）", ""]
        o = overview
        lines += [
            f"- 样本总数：{o['total']} 条；已披露金额：{o['priced_count']} 条，未披露：{o['unpriced_count']} 条",
            f"- 已披露金额合计：{o['amount_total_wan']} 万元；均值：{o['amount_avg_wan']} 万元；"
            f"中位数：{o['amount_median_wan']} 万元；区间：{o['amount_min_wan']} ~ {o['amount_max_wan']} 万元",
            "",
            "## 金额分档分布",
            "| 分档 | 数量 | 占比 | 金额合计(万元) |",
            "| --- | --- | --- | --- |",
        ]
        for d in band_dist:
            lines.append(f"| {d['band']} | {d['count']} | {d['share']:.1%} | {d['amount_total_wan']} |")

        for title, key in [("按品类", "by_category"), ("按客户类型", "by_buyer_type"),
                           ("按地区 TOP", "by_region"), ("按中标方", "by_winner")]:
            lines += ["", f"## {title}", "| 名称 | 项目数 | 金额合计(万元) | 均值(万元) | 最大(万元) |", "| --- | --- | --- | --- | --- |"]
            for d in analysis[key][:10]:
                lines.append(f"| {d['name']} | {d['count']} | {d['amount_total_wan']} | {d['amount_avg_wan']} | {d['max_wan']} |")

        lines += ["", "## 月度趋势", "| 月份 | 项目数 | 金额合计(万元) |", "| --- | --- | --- |"]
        for t in trend:
            lines.append(f"| {t['month']} | {t['count']} | {t['amount_total_wan']} |")

        lines += ["", "## 热点研判（待 Agent 撰写）",
                  "<!-- 结合上述数字，提炼：需求最集中的品类、客户类型与地区、单价区间、头部供应商集中度、趋势变化与机会点。 -->"]

        with open(args.report, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    print(f"analysis -> {args.out}; overview={overview}")


if __name__ == "__main__":
    main()
