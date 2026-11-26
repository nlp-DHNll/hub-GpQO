#!/usr/bin/env python3
"""
ESG / 双碳招标每日监控：新条目与存量库比对去重，按相关性打分生成推送清单。

输入：
  --new     当日新采集条目 JSON 数组（project, buyer, winner, amount_raw/amount_wan,
            date, region, url, summary, bid_type）
  --known   存量库 JSON（含 keys 数组；首次运行可省略）
  --out-list 新增条目 JSON 输出
  --report  推送简报 Markdown 输出
  --known-out 更新后的存量库 JSON（写入本次新增 key，供下次比对）

用法：
  python daily_watchlist.py --new today.json --known known.json \
      --out-list new.json --report daily-brief.md --known-out known.json
"""

import argparse
import json
import re
import unicodedata
from datetime import datetime

HOT_KEYWORDS = [
    "ESG", "可持续发展", "双碳", "碳达峰", "碳中和", "碳核算", "碳核查", "碳足迹",
    "碳账户", "绿色金融", "转型金融", "低碳", "气候", "绿色供应链", "CCUS",
    "绿色矿山", "披露", "评级",
]


def norm_key(text: str) -> str:
    t = unicodedata.normalize("NFKC", str(text)).lower()
    return re.sub(r"[\s\W_]+", "", t, flags=re.UNICODE)


def score(item: dict):
    text = f"{item.get('project', '')} {item.get('summary', '')} {item.get('buyer', '')}"
    hits = [k for k in HOT_KEYWORDS if k in text]
    score = min(1.0, 0.5 + 0.1 * len(hits))
    return round(score, 3), hits


def main():
    ap = argparse.ArgumentParser(description="每日招标监控去重与推送清单")
    ap.add_argument("--new", required=True)
    ap.add_argument("--known")
    ap.add_argument("--out-list", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--known-out")
    args = ap.parse_args()

    with open(args.new, encoding="utf-8") as f:
        new_items = json.load(f)

    known_keys = set()
    if args.known:
        try:
            with open(args.known, encoding="utf-8") as f:
                known = json.load(f)
            known_keys = set(known.get("keys", []))
        except FileNotFoundError:
            pass

    fresh, dup_count = [], 0
    for item in new_items:
        key = f"{norm_key(item['project'])}|{norm_key(item['buyer'])}"
        if key in known_keys:
            dup_count += 1
            continue
        s, hits = score(item)
        item["key"] = key
        item["score"] = s
        item["hits"] = hits
        fresh.append(item)

    fresh.sort(key=lambda x: x["score"], reverse=True)

    result = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "new_count": len(fresh),
            "duplicate_count": dup_count,
        },
        "items": fresh,
    }
    with open(args.out_list, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 推送简报
    lines = [f"# ESG / 双碳招标每日推送（{datetime.now().strftime('%Y-%m-%d')}）", ""]
    lines.append(f"今日新增 {len(fresh)} 条，剔除已收录重复 {dup_count} 条。")
    lines.append("")
    if not fresh:
        lines.append("- 今日无符合口径的新增招标信息。")
    for i, it in enumerate(fresh, 1):
        amount = it.get("amount_wan")
        amount_txt = f"预算/中标 {amount} 万元" if amount is not None else "金额未披露"
        lines.append(
            f"{i}. **{it['project']}**（{it.get('date', '')}，{it.get('region', '')}，{amount_txt}）"
        )
        lines.append(f"   - 采购人：{it['buyer']}；供应商：{it.get('winner', '待定')}")
        if it.get("summary"):
            lines.append(f"   - 摘要：{it['summary']}")
        lines.append(f"   - 命中标签：{ '、'.join(it['hits']) or '—' }；相关度 {it['score']}")
        if it.get("url"):
            lines.append(f"   - 链接：{it['url']}")
    with open(args.report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    if args.known_out:
        all_keys = known_keys | {it["key"] for it in fresh}
        with open(args.known_out, "w", encoding="utf-8") as f:
            json.dump({"keys": sorted(all_keys)}, f, ensure_ascii=False, indent=2)

    print(f"fresh={len(fresh)} duplicate={dup_count}")


if __name__ == "__main__":
    main()
