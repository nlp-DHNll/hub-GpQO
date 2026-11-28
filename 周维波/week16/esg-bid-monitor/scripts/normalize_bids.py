#!/usr/bin/env python3
"""
ESG / 双碳招投标条目标准化（确定性后处理脚本）。

输入 JSON 数组，原始字段：
  project    项目名称（必填）
  buyer      采购人（必填）
  winner     中标/成交方（可选）
  amount_raw 金额原文（可选，如 "120.00万元"、"1,200,000.00元"）
  amount_wan 已知万元金额（可选，优先于 amount_raw）
  date       公告日期 YYYY-MM-DD（必填）
  region     地区（可选）
  category   品类（可选，缺失按关键词兜底归类）
  bid_type   中标 | 招标（默认 中标）
  url / summary（可选）

完成：金额解析（统一为万元）、品类与客户类型归类、金额分档、键值去重。

用法：
  python normalize_bids.py --input raw-bids.json --out normalized.json
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime

CATEGORIES = {
    "esg_report": ["ESG报告", "可持续发展报告", "社会责任报告", "ESG咨询", "报告编制", "ESG服务", "数据治理"],
    "esg_rating": ["ESG评级", "评级管理", "评级提升"],
    "carbon_accounting": ["碳核算", "碳核查", "碳足迹", "碳账户", "碳排放", "碳数据", "排放核查"],
    "carbon_strategy": ["双碳", "碳达峰", "碳中和", "转型金融", "绿色金融", "节能", "降碳", "零碳", "低碳转型", "示范项目"],
    "certification": ["认证", "评估认证", "债券认证"],
    "green_supply_chain": ["绿色供应链", "环保管家", "绿色采购"],
}

BUYER_TYPES = {
    "financial": ["银行", "证券", "保险", "基金", "信托", "彩票", "交易所", "金融", "券商"],
    "gov": ["政府", "发改委", "管委会", "委员会", "厅", "局", "发展和改革", "研究院", "经济信息中心", "事业单位"],
    "enterprise": ["集团", "电力", "能源", "矿业", "煤", "铁投", "航", "机场", "铁塔", "燃气", "环保", "建设", "化工"],
}

BANDS = [
    ("重大(≥100万)", lambda v: v >= 100),
    ("大型(30-100万)", lambda v: 30 <= v < 100),
    ("中型(10-30万)", lambda v: 10 <= v < 30),
    ("小型(<10万)", lambda v: v < 10),
]


def norm_key(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[\s\W_]+", "", t, flags=re.UNICODE)


def parse_amount_wan(amount_wan, amount_raw):
    """返回万元数值；无法解析返回 None。"""
    if amount_wan is not None:
        try:
            return round(float(amount_wan), 4)
        except (TypeError, ValueError):
            pass
    if not amount_raw:
        return None
    s = str(amount_raw).replace(",", "").strip()
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*万元", s)
    if m:
        return round(float(m.group(1)), 4)
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*元", s)
    if m:
        return round(float(m.group(1)) / 10000.0, 4)
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", s)
    return round(float(m.group(1)) / 10000.0, 4) if m else None


def classify(text: str, rules: dict) -> str:
    for label, keys in rules.items():
        if any(k in text for k in keys):
            return label
    return "other"


def amount_band(value):
    if value is None:
        return "未披露"
    for label, fn in BANDS:
        if fn(value):
            return label
    return "未披露"


def main():
    ap = argparse.ArgumentParser(description="招投标条目标准化")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        raw = json.load(f)

    kept, seen, dropped = {}, {}, {"bad_date": 0, "duplicate": 0}

    for item in raw:
        try:
            datetime.strptime(item["date"], "%Y-%m-%d")
        except (KeyError, ValueError):
            dropped["bad_date"] += 1
            continue

        key = f"{norm_key(item['project'])}|{norm_key(item['buyer'])}"
        amount = parse_amount_wan(item.get("amount_wan"), item.get("amount_raw"))
        text = f"{item['project']} {item.get('summary', '')}"

        category = item.get("category") or classify(text, CATEGORIES)
        buyer_type = classify(item["buyer"], BUYER_TYPES)

        record = {
            "key": key,
            "project": item["project"].strip(),
            "buyer": item["buyer"].strip(),
            "winner": item.get("winner", "").strip(),
            "amount_wan": amount,
            "amount_band": amount_band(amount),
            "date": item["date"],
            "region": item.get("region", "").strip(),
            "category": category,
            "buyer_type": buyer_type,
            "bid_type": item.get("bid_type", "中标"),
            "url": item.get("url", ""),
            "summary": item.get("summary", "").strip(),
        }

        if key in seen:
            dropped["duplicate"] += 1
            # 保留金额更完整的一条
            prev = kept[key]
            if prev["amount_wan"] is None and amount is not None:
                kept[key] = record
            continue
        seen[key] = True
        kept[key] = record

    bids = list(kept.values())
    bids.sort(key=lambda b: b["date"], reverse=True)

    result = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total": len(bids),
            "dropped": dropped,
            "categories": list(CATEGORIES.keys()),
            "buyer_types": list(BUYER_TYPES.keys()) + ["other"],
        },
        "bids": bids,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"kept={len(bids)} dropped={dropped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
