"""从提炼结果导出来源清单 sources.jsonl，供报告引用和 check_report.py 复核。

用法：
  python sources.py --schema bid --in bids.jsonl --out sources.jsonl
  python sources.py --schema evidence --in cards.jsonl --out sources.jsonl [--min-relevance medium]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

RELEVANCE = {"irrelevant": 0, "low": 1, "medium": 2, "high": 3}
SECTION_ORDER = {"policy": 0, "rating": 1, "industry": 2, "company": 3, "peer": 4, "irrelevant": 5}


def from_evidence(rows: list[dict], min_rank: int) -> list[dict]:
    kept = [r for r in rows if r.get("card") and r["card"].get("section") != "irrelevant"
            and RELEVANCE.get(r["card"].get("relevance"), 0) >= min_rank]
    kept.sort(key=lambda r: (SECTION_ORDER.get(r["card"]["section"], 9), r.get("published") or ""))
    return [{"title": r["card"].get("title") or r.get("title"), "publisher": r["card"].get("publisher", ""),
             "published": r.get("published", ""), "url": r.get("url", ""), "section": r["card"]["section"],
             "verified": r.get("basis") == "fulltext"} for r in kept]


def from_bid(rows: list[dict]) -> list[dict]:
    def day(r: dict):
        return c.to_date(r.get("published", "")) or date.min

    cards = [r for r in rows if r.get("card") and r["card"].get("is_esg")
             and r["card"].get("notice_type") in ("award", "tender")]
    ordered = (sorted([r for r in cards if r["card"]["notice_type"] == "award"], key=day, reverse=True)
               + sorted([r for r in cards if r["card"]["notice_type"] == "tender"], key=day, reverse=True))
    return [{"title": r["card"].get("project") or r.get("title"), "publisher": r["card"].get("purchaser", ""),
             "published": r.get("published", ""), "url": r.get("url", ""), "section": "bid",
             "notice_type": r["card"]["notice_type"], "amount_wan": r["card"].get("amount_wan"),
             "verified": r.get("basis") == "fulltext"} for r in ordered]


def main() -> int:
    c.init()
    ap = argparse.ArgumentParser(description="导出来源清单 sources.jsonl")
    ap.add_argument("--schema", choices=["evidence", "bid"], required=True)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-relevance", choices=["low", "medium", "high"], default="medium",
                    help="evidence 模式：只导出相关性不低于该值的卡片")
    args = ap.parse_args()

    rows = c.read_jsonl(args.inp)
    kept = from_evidence(rows, RELEVANCE[args.min_relevance]) if args.schema == "evidence" else from_bid(rows)
    n = c.write_jsonl(args.out, [dict(id=f"S{i}", **s) for i, s in enumerate(kept, 1)])
    opened = sum(1 for s in kept if s["verified"])
    print(f"[sources] 导出 {n} 条，其中打开过原文 {opened} 条，仅依据摘要 {n - opened} 条，输出={args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(c.guard("sources", main))
