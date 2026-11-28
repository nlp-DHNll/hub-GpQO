#!/usr/bin/env python3
"""ESG 情报证据字段检查脚本。只检查数据完整性和格式，不联网验证事实。"""
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
from urllib.parse import urlparse

VALID_STATUS = {"verified","partially_verified","unverified","pending","not_applicable"}
VALID_SOURCE_TYPE = {"primary","secondary","aggregator","user_provided","unknown"}

def main():
    ap = argparse.ArgumentParser(description="检查 ESG 情报证据字段完整性（不验证网页真实性）")
    ap.add_argument("input")
    ap.add_argument("-o","--output")
    args = ap.parse_args()
    data = load_json(args.input)
    items = get_items(data)
    results = []
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            results.append({"record": i, "severity":"error", "issue":"记录不是对象"})
            continue
        issues = []
        for field in ("title","summary","source_name","source_title","source_url","verification_status"):
            if not item.get(field):
                issues.append({"severity":"error" if field in ("title","source_url") else "warning",
                               "field":field,"issue":"字段缺失"})
        for field in ("event_date","publish_date"):
            if item.get(field) and normalize_date(item[field]) is None:
                issues.append({"severity":"warning","field":field,"issue":"日期格式无法识别"})
        url = item.get("source_url")
        if url and not valid_http_url(url):
            issues.append({"severity":"error","field":"source_url","issue":"URL 格式无效"})
        status = item.get("verification_status")
        if status and status not in VALID_STATUS:
            issues.append({"severity":"error","field":"verification_status","issue":"核验状态不在允许值范围"})
        stype = item.get("source_type")
        if stype and stype not in VALID_SOURCE_TYPE:
            issues.append({"severity":"warning","field":"source_type","issue":"来源类型不在允许值范围"})
        if status in ("pending","unverified","partially_verified"):
            issues.append({"severity":"warning","field":"verification_status","issue":"该记录尚未完全核实，引用时应保留提示"})
        if item.get("publish_date") and item.get("event_date"):
            p, e = normalize_date(item["publish_date"]), normalize_date(item["event_date"])
            if p and e and e > p:
                issues.append({"severity":"warning","field":"event_date","issue":"事件日期晚于发布日期，请核对是否录入错误"})
        results.append({"item_id":item.get("item_id"),"title":item.get("title"),"issues":issues,
                        "passed":not any(x["severity"]=="error" for x in issues)})
    counts = {"records":len(results),"errors":0,"warnings":0,"passed":0}
    for r in results:
        for issue in r.get("issues",[]):
            counts["errors" if issue["severity"]=="error" else "warnings"] += 1
        if r.get("passed"): counts["passed"] += 1
    save_json({"summary":counts,"items":results,
               "disclaimer":"仅检查字段完整性和格式；未访问 URL，未判断来源真实性或内容是否支持事实。"}, args.output)

if __name__ == "__main__":
    main()
