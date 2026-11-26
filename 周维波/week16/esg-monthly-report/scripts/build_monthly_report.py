#!/usr/bin/env python3
"""
基于清洗打分后的信号 JSON，生成 ESG 月报 Markdown 骨架（确定性排版）。

脚本只负责：按板块归集信号、固定章节顺序、渲染条目与信源清单；
研判、影响分析、建议等需要主观判断的内容保留占位，由 Agent 结合素材撰写。

用法：
  python build_monthly_report.py --input cleaned.json --out report.md \
      --client 中国神华 --industry 煤炭 能源
"""

import argparse
import json
from datetime import datetime

SECTIONS = [
    ("policy", "二、ESG 政策、评级与标准动态"),
    ("industry", "三、行业动态与最佳实践"),
    ("company", "四、客户公司 ESG 影响研判与建议"),
    ("peer", "五、对标企业 ESG 关键行动"),
]

SECTION_HINT = {
    "policy": "梳理本月新出台/修订的披露准则、监管规则、评级方法论、鉴证标准；标注生效时间、适用范围与对客户的合规含义。",
    "industry": "归集客户所属行业的政策导向、技术路线、标杆实践与争议事件；提炼可借鉴的最佳实践。",
    "company": "基于公司公告、新闻、ESG 报告与评级变动，研判本月动态对 E/S/G 各维度的影响，并给出可落地的改进建议。",
    "peer": "选取 2~4 家同行业对标企业，按绿色转型、治理架构、披露与评级、供应链责任等维度对照关键行动。",
}


def render_signal(sig: dict) -> str:
    title = sig["title"]
    date = sig["date"]
    source = sig["source"]
    summary = sig.get("summary", "").strip()
    url = sig.get("url", "")
    entity = sig.get("entity", "")
    score = sig.get("score")
    meta = f"{date}，{source}"
    if entity:
        meta += f"，主体：{entity}"
    if score is not None:
        meta += f"，相关度 {score}"
    link = f"[原文]({url})" if url else ""
    line = f"- **{title}**（{meta}）"
    if summary:
        line += f"。{summary}"
    if link:
        line += f" {link}"
    return line


def main():
    ap = argparse.ArgumentParser(description="生成 ESG 月报 Markdown 骨架")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--client", default="客户")
    ap.add_argument("--industry", nargs="*", default=[])
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    meta = data["meta"]
    start, end = meta["window"]["start"], meta["window"]["end"]
    signals = data["signals"]
    by_cat = {c: [] for c, _ in SECTIONS}
    for sig in signals:
        by_cat.setdefault(sig["category"], []).append(sig)

    lines = []
    lines.append(f"# {args.client} ESG 月报（{start} ~ {end}）")
    lines.append("")
    lines.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　|　"
                 f"收录信号 {meta['total']} 条　|　行业：{'、'.join(args.industry) or '未指定'}")
    lines.append("")

    lines.append("## 一、本月摘要")
    lines.append("<!-- 待撰写：基于下列各板块信号，提炼 3~5 条核心结论，覆盖政策合规压力、行业趋势、公司表现与行动建议。 -->")
    lines.append("")

    for cat, heading in SECTIONS:
        lines.append(f"## {heading}")
        lines.append(f"<!-- 口径：{SECTION_HINT[cat]} -->")
        bucket = by_cat.get(cat, [])
        if not bucket:
            lines.append("- 本周期未检索到符合口径的信号，可放宽关键词或扩大信源后复查。")
        for sig in bucket:
            lines.append(render_signal(sig))
        lines.append("")

    lines.append("## 六、风险提示与跟踪事项")
    lines.append("<!-- 待撰写：需持续跟踪的监管节点、评级窗口、行业事件与公司待披露事项。 -->")
    lines.append("")

    lines.append("## 附录：信源清单")
    for i, sig in enumerate(signals, 1):
        lines.append(f"{i}. {sig['source']}｜{sig['title']}｜{sig['date']}｜{sig.get('url', '')}")
    lines.append("")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"report skeleton -> {args.out} ({meta['total']} signals)")


if __name__ == "__main__":
    main()
