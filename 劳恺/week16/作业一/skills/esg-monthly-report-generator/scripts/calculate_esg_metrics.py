#!/usr/bin/env python3
"""ESG 月度情报基础指标统计脚本。只做计数和分布统计，不代替趋势分析。"""
"""Shared helpers are intentionally duplicated in standalone scripts to keep each script portable."""
import json, re, sys
from pathlib import Path
from datetime import date, datetime

def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)

def save_json(data, path):
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    else:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        print()

def get_items(data, key="items"):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        value = data.get(key, [])
        return value if isinstance(value, list) else []
    raise ValueError("输入 JSON 顶层必须是数组或包含数组字段的对象")

def clean_text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or None

def normalize_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        return None

def valid_http_url(value):
    return isinstance(value, str) and bool(re.match(r"^https?://[^\s]+$", value.strip(), re.I))

def read_text(path):
    return Path(path).read_text(encoding="utf-8-sig")

import argparse
from collections import Counter
from datetime import date

def main():
    ap = argparse.ArgumentParser(description="统计 ESG 情报基础指标，不替代趋势分析")
    ap.add_argument("input")
    ap.add_argument("--month", help="统计月份 YYYY-MM；默认使用当前月份")
    ap.add_argument("-o","--output")
    args = ap.parse_args()
    data = load_json(args.input)
    items = get_items(data)
    month = args.month or date.today().strftime("%Y-%m")
    selected = [x for x in items if isinstance(x,dict) and
                ((x.get("publish_date") or x.get("event_date") or "")[:7] == month)]
    def counts(field):
        return dict(Counter((x.get(field) or "未分类") for x in selected))
    result = {
        "report_month":month,
        "total_input_records":len(items),
        "records_in_month":len(selected),
        "category_distribution":counts("category"),
        "relevance_distribution":counts("relevance"),
        "verification_distribution":counts("verification_status"),
        "source_type_distribution":counts("source_type"),
        "high_relevance_items":[
            {"item_id":x.get("item_id"),"company":x.get("company"),"title":x.get("title"),
             "category":x.get("category"),"publish_date":x.get("publish_date")}
            for x in selected if x.get("relevance")=="high"
        ],
        "method_note":"按 publish_date 优先、event_date 兜底筛选月份；仅为数量统计，不代表重要性或趋势结论。"
    }
    save_json(result,args.output)

if __name__ == "__main__":
    main()
