#!/usr/bin/env python3
"""ESG 情报数据标准化脚本。输入 JSON，输出规范化记录、警告和潜在重复项。"""
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

import argparse, hashlib, re
from collections import Counter

CATEGORY_MAP = {
    "政策": "政策法规", "法规": "政策法规", "政策法规": "政策法规",
    "环境": "环境与气候", "气候": "环境与气候", "双碳": "环境与气候", "环境与气候": "环境与气候",
    "社会": "社会责任", "社会责任": "社会责任",
    "治理": "公司治理", "公司治理": "公司治理",
    "评级": "ESG评级与披露", "披露": "ESG评级与披露", "ESG评级与披露": "ESG评级与披露",
    "同行": "同行实践", "同行实践": "同行实践"
}
ALLOWED_RELEVANCE = {"high", "medium", "low", "unknown"}
ALLOWED_SOURCE_TYPE = {"primary", "secondary", "aggregator", "user_provided", "unknown"}
ALLOWED_VERIFICATION = {"verified", "partially_verified", "unverified", "pending", "not_applicable"}

def main():
    ap = argparse.ArgumentParser(description="标准化 ESG 情报 JSON 数据")
    ap.add_argument("input", help="输入 JSON 文件")
    ap.add_argument("-o", "--output", help="输出 JSON 文件；省略则输出到终端")
    args = ap.parse_args()
    raw = load_json(args.input)
    records = get_items(raw)
    output, warnings = [], []
    for idx, original in enumerate(records, 1):
        if not isinstance(original, dict):
            warnings.append({"record": idx, "issue": "记录不是 JSON 对象，已跳过"})
            continue
        item = dict(original)
        for key in ("company","title","category","industry","summary","analysis","relevance_reason",
                    "source_name","source_title","source_url","notes"):
            if key in item:
                item[key] = clean_text(item[key])
        for key in ("event_date","publish_date"):
            if item.get(key) not in (None, ""):
                normalized = normalize_date(item[key])
                if normalized is None:
                    warnings.append({"record": idx, "field": key, "value": item[key], "issue": "日期无法识别，保留原值"})
                else:
                    item[key] = normalized
            else:
                item[key] = None
        category = item.get("category")
        if category:
            item["category"] = CATEGORY_MAP.get(category, category)
        for field, allowed, default in (
            ("relevance", ALLOWED_RELEVANCE, "unknown"),
            ("source_type", ALLOWED_SOURCE_TYPE, "unknown"),
            ("verification_status", ALLOWED_VERIFICATION, "pending")
        ):
            value = item.get(field)
            if value not in allowed:
                if value not in (None, ""):
                    warnings.append({"record": idx, "field": field, "value": value, "issue": "不在允许值范围，已设为默认值"})
                item[field] = default
        if not item.get("item_id"):
            basis = "|".join(str(item.get(k) or "") for k in ("company","title","event_date","source_url"))
            item["item_id"] = "ESG-" + hashlib.sha1((basis or str(idx)).encode("utf-8")).hexdigest()[:12]
        if not item.get("title"):
            warnings.append({"record": idx, "field": "title", "issue": "缺少标题"})
        output.append(item)
    # Conservative duplicate flag: do not delete records automatically.
    seen, duplicates = {}, []
    for item in output:
        key = (re.sub(r"\W+", "", (item.get("company") or "") + (item.get("title") or "")).lower(),
               item.get("event_date"))
        if key in seen:
            duplicates.append({"item_id": item["item_id"], "possible_duplicate_of": seen[key]})
        else:
            seen[key] = item["item_id"]
    result = {
        "schema_version": "1.0",
        "generated_at": date.today().isoformat(),
        "items": output,
        "processing_summary": {
            "input_records": len(records), "output_records": len(output),
            "warning_count": len(warnings), "possible_duplicate_count": len(duplicates)
        },
        "warnings": warnings,
        "possible_duplicates": duplicates
    }
    save_json(result, args.output)

if __name__ == "__main__":
    from datetime import date
    main()
