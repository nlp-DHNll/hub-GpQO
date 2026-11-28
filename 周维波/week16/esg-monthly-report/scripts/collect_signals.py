#!/usr/bin/env python3
"""
ESG 月报信号清洗与打分（确定性后处理脚本）。

输入：JSON 数组，每条信号字段：
  title      标题（必填）
  date       发布日期 YYYY-MM-DD（必填）
  source     来源名称（必填）
  url        链接（必填，用于去重）
  category   policy | industry | company | peer（必填，缺失时按关键词兜底归类）
  summary    摘要（必填）
  tags       标签数组（可选）
  relevance  人工/模型预打相关性 0~1（可选，默认 0.5）
  entity     关联主体（客户名或对标企业名，可选）

功能：
  1. 时效过滤：仅保留 [--start, --end] 窗口内信号（默认最近 31 天）；
  2. 去重：URL 去重 + 标题归一化去重；
  3. 分类校验与兜底归类；
  4. 可解释打分：相关性 * 0.6 + 时效 * 0.2 + 权威源 * 0.1 + 行业命中 * 0.1；
  5. 输出排序后的结构化 JSON 与计数摘要。

用法：
  python collect_signals.py --input signals.json --out cleaned.json \
      --start 2026-10-26 --end 2026-11-26 --industry 煤炭 煤电 煤化工 新能源 绿色矿山
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import date, datetime

CATEGORIES = {"policy", "industry", "company", "peer"}

# 权威信源域名关键词（命中即加权威分）
AUTHORITY_HINTS = (
    "gov.cn", "csrc.gov", "nea.gov", "mee.gov", "ndrc.gov", "sasac.gov",
    "sse.com.cn", "szse.cn", "hkex", "cnstock.com", "people.com.cn",
    "xinhuanet", "gmw.cn", "ce.cn", "cnr.cn", "caixin",
)

# 分类兜底关键词（category 缺失时使用）
CATEGORY_RULES = [
    ("policy", ["政策", "指引", "准则", "标准", "规划", "方案", "评级", "方法论", "监管", "披露", "鉴证", "指南"]),
    ("peer", ["对标", "同行", "中煤", "陕煤", "兖矿", "晋能", "对标企业"]),
    ("company", ["公司", "神华", "集团", "电厂", "煤矿", "项目", "获奖", "入选"]),
]


def parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def normalize_title(title: str) -> str:
    """标题归一化：去标点、空白、大小写，用于去重。"""
    t = unicodedata.normalize("NFKC", title).lower()
    return re.sub(r"[\s\W_]+", "", t, flags=re.UNICODE)


def classify(text: str) -> str:
    for cat, keys in CATEGORY_RULES:
        if any(k in text for k in keys):
            return cat
    return "industry"


def authority_score(url: str, source: str) -> float:
    blob = f"{url} {source}".lower()
    return 1.0 if any(h in blob for h in AUTHORITY_HINTS) else 0.0


def industry_hit(text: str, industry_keywords) -> float:
    if not industry_keywords:
        return 0.0
    return 1.0 if any(k in text for k in industry_keywords) else 0.0


def score_signal(sig, start: date, end: date, industry_keywords):
    reasons = []
    rel = float(sig.get("relevance", 0.5))
    rel = min(max(rel, 0.0), 1.0)

    days_old = (end - sig["_date"]).days
    if days_old < 0:
        recency = 0.0
    else:
        recency = max(0.2, 1.0 - 0.1 * (days_old // 7))
    reasons.append(f"时效{recency:.2f}")

    auth = authority_score(sig["url"], sig["source"])
    if auth:
        reasons.append("权威源")

    text = f"{sig['title']} {sig['summary']} {' '.join(sig.get('tags', []))}"
    ind = industry_hit(text, industry_keywords)
    if ind:
        reasons.append("行业命中")

    score = rel * 0.6 + recency * 0.2 + auth * 0.1 + ind * 0.1
    sig["score"] = round(min(max(score, 0.0), 1.0), 3)
    sig["score_reasons"] = reasons
    return sig


def main():
    ap = argparse.ArgumentParser(description="ESG 月报信号清洗与打分")
    ap.add_argument("--input", required=True, help="原始信号 JSON 文件")
    ap.add_argument("--out", required=True, help="清洗后 JSON 输出路径")
    ap.add_argument("--start", help="报告期起始 YYYY-MM-DD，默认 31 天前")
    ap.add_argument("--end", help="报告期截止 YYYY-MM-DD，默认今天")
    ap.add_argument("--industry", nargs="*", default=[], help="客户所属行业关键词")
    args = ap.parse_args()

    end = parse_date(args.end) if args.end else date.today()
    start = parse_date(args.start) if args.start else date.fromordinal(end.toordinal() - 31)

    with open(args.input, encoding="utf-8") as f:
        raw = json.load(f)

    seen_url, seen_title, kept = set(), set(), []
    dropped = {"bad_date": 0, "out_of_window": 0, "duplicate": 0}

    for item in raw:
        try:
            d = parse_date(item["date"])
        except (KeyError, ValueError):
            dropped["bad_date"] += 1
            continue
        if not (start <= d <= end):
            dropped["out_of_window"] += 1
            continue

        url = item.get("url", "").strip()
        norm_title = normalize_title(item["title"])
        if url and url in seen_url:
            dropped["duplicate"] += 1
            continue
        if norm_title in seen_title:
            dropped["duplicate"] += 1
            continue

        category = item.get("category") or ""
        if category not in CATEGORIES:
            category = classify(f"{item['title']} {item.get('summary', '')}")
        item["category"] = category
        item["_date"] = d
        item["date"] = d.isoformat()

        seen_url.add(url)
        seen_title.add(norm_title)
        kept.append(item)

    for sig in kept:
        score_signal(sig, start, end, args.industry)
        sig.pop("_date", None)

    kept.sort(key=lambda s: s["score"], reverse=True)

    counts = {c: 0 for c in CATEGORIES}
    for sig in kept:
        counts[sig["category"]] += 1

    result = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "total": len(kept),
            "by_category": counts,
            "dropped": dropped,
        },
        "signals": kept,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"kept={len(kept)} dropped={dropped} by_category={counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
