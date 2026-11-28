#!/usr/bin/env python3
"""ESG 行动计划跟踪脚本。汇总状态、逾期、近期到期及跨月状态变化。"""
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
from datetime import date, timedelta

VALID={"not_started","in_progress","blocked","completed","overdue","cancelled"}

def main():
    ap=argparse.ArgumentParser(description="汇总 ESG 月报行动计划状态和到期情况")
    ap.add_argument("input",help="action_tracker.json")
    ap.add_argument("--previous",help="上月 action_tracker.json，可选")
    ap.add_argument("--as-of",help="统计日期 YYYY-MM-DD；默认今天")
    ap.add_argument("--upcoming-days",type=int,default=30)
    ap.add_argument("-o","--output")
    args=ap.parse_args()
    as_of=normalize_date(args.as_of) if args.as_of else date.today().isoformat()
    if not as_of: ap.error("--as-of 日期格式无效")
    today=date.fromisoformat(as_of)
    data=load_json(args.input)
    actions=get_items(data,"actions")
    previous={}
    if args.previous:
        pdata=load_json(args.previous)
        previous={x.get("action_id"):x for x in get_items(pdata,"actions") if isinstance(x,dict) and x.get("action_id")}
    rows=[]; counts={}
    for x in actions:
        if not isinstance(x,dict): continue
        status=x.get("status") or "not_started"
        if status not in VALID: status="unknown"
        due=normalize_date(x.get("due_date"))
        due_dt=date.fromisoformat(due) if due else None
        derived="overdue" if due_dt and due_dt < today and status not in ("completed","cancelled") else status
        days=(due_dt-today).days if due_dt else None
        prior=previous.get(x.get("action_id"))
        rows.append({
            "action_id":x.get("action_id"),"action":x.get("action"),"priority":x.get("priority"),
            "owner":x.get("owner"),"due_date":due,"recorded_status":status,
            "tracking_status":derived,"days_to_due":days,
            "due_soon":days is not None and 0 <= days <= args.upcoming_days and derived not in ("completed","cancelled"),
            "previous_status":prior.get("status") if prior else None,
            "status_changed":bool(prior and prior.get("status") != status),
            "is_carry_over":bool(prior)
        })
        counts[derived]=counts.get(derived,0)+1
    result={
        "as_of":as_of,"total_actions":len(rows),"status_counts":counts,
        "overdue_actions":[r for r in rows if r["tracking_status"]=="overdue"],
        "upcoming_actions":[r for r in rows if r["due_soon"]],
        "changed_actions":[r for r in rows if r["status_changed"]],
        "actions":rows,
        "note":"逾期状态由截止日期和当前记录状态推导；脚本不判断工作是否实质完成。请核实状态变更依据。"
    }
    save_json(result,args.output)

if __name__=="__main__":
    main()
