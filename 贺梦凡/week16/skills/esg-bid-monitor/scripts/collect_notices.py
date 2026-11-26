#!/usr/bin/env python3
"""Search tender notices and emit records for analyze_bids.py.

Amounts are taken only from a labeled 中标/成交 phrase in the opened page.
Budget-only pages stay amount-empty. Excerpts are copied, not rewritten.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_lib"))
from web_collect import collect  # noqa: E402

DEFAULT_QUERIES = [
    "2026 ESG报告 编制 中标公告",
    "2026 碳核查 OR 碳盘查 中标公告",
    "2026 双碳 OR 碳达峰 咨询 中标",
]
KEYWORDS = ("ESG", "可持续发展", "双碳", "碳达峰", "碳中和", "碳核查", "碳盘查", "碳排放", "环境信息")
AWARD = re.compile(
    r"(中标金额|成交金额|中标价|成交价)[:：]?\s*(\d+(?:\.\d+)?)\s*(亿元|亿|万元|万|元)?"
)
BUDGET = re.compile(r"预算|限价|控制价")


def to_yuan(number: str, unit: str | None) -> float:
    value = float(number)
    if unit in ("亿元", "亿"):
        return value * 100_000_000
    if unit in ("万元", "万"):
        return value * 10_000
    return value


def doc_type(title: str) -> str:
    if "成交" in title:
        return "成交公告"
    if "中标" in title:
        return "中标公告"
    if "候选人" in title:
        return "候选人公示"
    if "采购意向" in title:
        return "采购意向"
    if "招标" in title:
        return "招标公告"
    return "类型不明"


def topic_of(text: str) -> str:
    if any(word in text for word in ("碳核查", "碳盘查", "温室气体")):
        return "碳核算与核查"
    if "信息披露" in text:
        return "环境信息披露系统"
    if any(word in text for word in ("碳达峰", "碳中和", "双碳")):
        return "双碳规划咨询"
    if "ESG" in text.upper() or "可持续发展" in text:
        return "ESG报告与评级"
    return "其他ESG相关"


def records_from(result: dict) -> list[dict]:
    records = []
    for item in result["items"]:
        if not item.get("opened"):
            continue
        blob = item.get("excerpt") or ""
        if not any(word.lower() in blob.lower() for word in KEYWORDS):
            continue
        match = AWARD.search(blob)
        amount = None
        amount_raw = ""
        if match and not BUDGET.search(match.group(0)):
            amount = to_yuan(match.group(2), match.group(3))
            amount_raw = match.group(0)
        day = re.search(r"(20\d{2})[年\-.](\d{1,2})[月\-.](\d{1,2})", blob)
        publish = (
            f"{int(day.group(1)):04d}-{int(day.group(2)):02d}-{int(day.group(3)):02d}"
            if day
            else ""
        )
        if not publish:
            continue
        records.append(
            {
                "title": item["title"],
                "url": item["url"],
                "publish_date": publish,
                "buyer": "未注明",
                "winner": "未注明",
                "region": "未注明地区",
                "topic": topic_of(blob),
                "doc_type": doc_type(item["title"]),
                "amount_cny": amount,
                "amount_raw": amount_raw,
                "include_reason": blob[:80],
                "source_name": item["domain"],
            }
        )
    return records


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="检索招标公告并抽出可统计记录")
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--per-query", type=int, default=4)
    parser.add_argument("--max-pages", type=int, default=6)
    parser.add_argument("--since", default="2024-11-26")
    parser.add_argument("--until", default="2026-11-26")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv[1:])
    result = collect(
        args.queries or DEFAULT_QUERIES,
        datetime.strptime(args.since, "%Y-%m-%d"),
        datetime.strptime(args.until, "%Y-%m-%d"),
        KEYWORDS,
        per_query=args.per_query,
        max_pages=args.max_pages,
        deadline_sec=70,
    )
    records = records_from(result)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"打开 {result['opened_count']}，抽出 {len(records)} 条记录，用时 {result['elapsed_sec']}s")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
