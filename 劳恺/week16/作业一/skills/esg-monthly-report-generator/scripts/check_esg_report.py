#!/usr/bin/env python3
"""ESG 月报质量规则检查脚本。检查重复内容、证据台账和行动计划字段。"""
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

import argparse, re
from collections import Counter
from datetime import date

def repeated_paragraphs(text):
    paras = [re.sub(r"\s+"," ",p).strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) >= 25]
    c = Counter(paras)
    return [{"paragraph":p[:300],"count":n} for p,n in c.items() if n > 1]

def main():
    ap = argparse.ArgumentParser(description="月报规则检查：重复段落、证据台账、行动计划")
    ap.add_argument("--report", help="Markdown/TXT 报告文件")
    ap.add_argument("--evidence", help="evidence_ledger.json")
    ap.add_argument("--actions", help="action_tracker.json")
    ap.add_argument("-o","--output")
    args = ap.parse_args()
    if not any((args.report,args.evidence,args.actions)):
        ap.error("至少提供 --report、--evidence 或 --actions 之一")
    findings = []
    report_text = read_text(args.report) if args.report else ""
    if args.report:
        for p in repeated_paragraphs(report_text):
            findings.append({"severity":"warning","type":"repeated_paragraph","detail":p})
        # Repeated sentence check is heuristic; avoid treating short boilerplate as definite error.
        sentences = [re.sub(r"\s+","",s).strip() for s in re.split(r"[。！？；\n]",report_text) if len(s.strip()) >= 18]
        for s,n in Counter(sentences).items():
            if n > 1:
                findings.append({"severity":"warning","type":"repeated_sentence","detail":{"sentence":s[:240],"count":n}})
        # Detect explicitly mentioned "待核实" as a reminder, not a defect.
        if "待核实" in report_text:
            findings.append({"severity":"info","type":"pending_fact_marker","detail":"报告含“待核实”标记，请确认正文已说明原因和后续核验安排"})
    evidence_ids = set()
    if args.evidence:
        ev = load_json(args.evidence)
        for i,x in enumerate(get_items(ev),1):
            if not isinstance(x,dict):
                findings.append({"severity":"error","type":"invalid_evidence_record","detail":{"record":i}})
                continue
            eid=x.get("evidence_id")
            if not eid:
                findings.append({"severity":"error","type":"missing_evidence_id","detail":{"record":i}})
            elif eid in evidence_ids:
                findings.append({"severity":"error","type":"duplicate_evidence_id","detail":eid})
            evidence_ids.add(eid)
            for f in ("claim","source_name","source_title","source_url","verification_status"):
                if not x.get(f):
                    findings.append({"severity":"warning","type":"missing_evidence_field","detail":{"evidence_id":eid,"field":f}})
            if x.get("source_url") and not valid_http_url(x["source_url"]):
                findings.append({"severity":"warning","type":"invalid_source_url","detail":{"evidence_id":eid,"url":x["source_url"]}})
            if x.get("verification_status") in ("pending","unverified","partially_verified"):
                findings.append({"severity":"warning","type":"unverified_evidence","detail":{"evidence_id":eid,"status":x.get("verification_status")}})
            if not x.get("section"):
                findings.append({"severity":"warning","type":"missing_report_section","detail":{"evidence_id":eid}})
    if args.actions:
        ac=load_json(args.actions)
        ids=set()
        for i,x in enumerate(get_items(ac,"actions"),1):
            if not isinstance(x,dict): continue
            aid=x.get("action_id")
            if not aid:
                findings.append({"severity":"error","type":"missing_action_id","detail":{"record":i}})
            elif aid in ids:
                findings.append({"severity":"error","type":"duplicate_action_id","detail":aid})
            ids.add(aid)
            due=normalize_date(x.get("due_date"))
            start=normalize_date(x.get("start_date"))
            if x.get("due_date") and not due:
                findings.append({"severity":"warning","type":"invalid_due_date","detail":{"action_id":aid,"value":x.get("due_date")}})
            if start and due and due < start:
                findings.append({"severity":"error","type":"deadline_before_start","detail":{"action_id":aid,"start_date":start,"due_date":due}})
            horizon=x.get("horizon")
            if due and horizon in ("short","medium","long"):
                # 时间边界由报告自行定义，脚本不做硬性比较，只提示核对。
                findings.append({"severity":"info","type":"check_horizon_definition","detail":{"action_id":aid,"message":"请对照报告中自行定义的短中长期时间范围核对截止日期"}})
            for eid in x.get("related_evidence_ids",[]) or []:
                if args.evidence and eid not in evidence_ids:
                    findings.append({"severity":"warning","type":"unknown_related_evidence_id","detail":{"action_id":aid,"evidence_id":eid}})
    summary=Counter(x["severity"] for x in findings)
    save_json({"summary":{"errors":summary.get("error",0),"warnings":summary.get("warning",0),"info":summary.get("info",0)},
               "findings":findings,
               "limitations":"规则检查不能证明事实真实性、来源支持关系或复杂时间分类是否合理；需结合报告定义和原始来源复核。"},args.output)

if __name__ == "__main__":
    main()
