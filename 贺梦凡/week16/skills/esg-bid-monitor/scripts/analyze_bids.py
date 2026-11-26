#!/usr/bin/env python3
"""Dedupe ESG bid records and compute topic and amount statistics."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

KEYWORDS = [
    "esg",
    "可持续发展",
    "双碳",
    "碳达峰",
    "碳中和",
    "碳核查",
    "碳盘查",
    "温室气体",
    "碳排放",
    "碳资产",
    "ccer",
    "tcfd",
    "issb",
    "gri",
    "气候",
    "环境信息披露",
    "绿色金融",
]
AWARDS = {"中标公告", "成交公告"}
DOC_TYPES = ["招标公告", "采购意向", "候选人公示", "中标公告", "成交公告", "类型不明"]
BUDGET_WORD = re.compile(r"预算|限价|控制价|最高价")
BINS = [
    (0, 500_000, "50万元以下"),
    (500_000, 1_000_000, "50万–100万元"),
    (1_000_000, 3_000_000, "100万–300万元"),
    (3_000_000, 10_000_000, "300万–1000万元"),
    (10_000_000, 100_000_000, "1000万元–1亿元"),
    (100_000_000, math.inf, "1亿元及以上"),
]


def canon_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parts.query) if not key.lower().startswith("utm_")]
    )
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def norm_text(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", (value or "").lower(), flags=re.UNICODE)


def convert_amount(number: float, unit: str) -> float:
    if unit in ("亿元", "亿"):
        return number * 100_000_000
    if unit in ("万元", "万"):
        return number * 10_000
    return number


def parse_amount(raw) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    text = str(raw).strip().replace(",", "").replace("，", "").replace(" ", "")
    for token in ("人民币", "RMB", "CNY", "￥", "¥"):
        text = text.replace(token, "")
    match = re.search(r"(\d+(?:\.\d+)?)(亿元|亿|万元|万|元)?", text)
    if not match:
        return None
    return convert_amount(float(match.group(1)), match.group(2) or "元")


def parse_labeled_award(raw: str) -> float | None:
    text = str(raw or "").replace(",", "").replace("，", "").replace(" ", "")
    match = re.search(
        r"(?:中标金额|成交金额|中标价|成交价)[:：]?(\d+(?:\.\d+)?)(亿元|亿|万元|万|元)?",
        text,
    )
    if not match:
        return None
    return convert_amount(float(match.group(1)), match.group(2) or "元")


def infer_doc_type(title: str) -> str:
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


def has_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in KEYWORDS)


def parse_day(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def fmt_yuan(amount: float) -> str:
    if amount >= 100_000_000:
        return f"{amount / 100_000_000:.2f}亿元"
    return f"{amount / 10_000:.2f}万元"


def median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def load_rows(path: str) -> list:
    with open(path, encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("JSON 必须是数组")
    return data


def clean_row(raw: dict, index: int) -> tuple[dict | None, str | None]:
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "").strip()
    if not title or not url:
        return None, f"第{index}条缺少标题或链接，已丢弃"
    reason = str(raw.get("include_reason") or "").strip()
    if not has_keyword(reason):
        return None, f"第{index}条《{title}》的纳入依据没有关键词，已丢弃"
    day = parse_day(str(raw.get("publish_date") or ""))
    if day is None:
        return None, f"第{index}条《{title}》的日期不是 YYYY-MM-DD，已丢弃"
    doc_type = str(raw.get("doc_type") or "").strip() or infer_doc_type(title)
    if doc_type not in DOC_TYPES:
        doc_type = infer_doc_type(title)
    explicit = raw.get("amount_cny")
    raw_text = str(raw.get("amount_raw") or "")
    labeled = parse_labeled_award(raw_text)
    if labeled is not None:
        parsed_raw = labeled
    elif BUDGET_WORD.search(raw_text):
        parsed_raw = None
    else:
        parsed_raw = parse_amount(raw_text)
    amount = None
    note = None
    if explicit not in (None, ""):
        try:
            amount = float(explicit)
        except (TypeError, ValueError):
            note = f"第{index}条金额不是数字，已改用原文里的中标金额"
            amount = parsed_raw
        else:
            if parsed_raw and amount > 0 and parsed_raw > 0 and max(amount, parsed_raw) / min(amount, parsed_raw) > 10:
                note = f"第{index}条 amount_cny 与 amount_raw 相差超过 10 倍，统计暂用 amount_cny，请核对单位是否为元"
    elif parsed_raw is not None:
        amount = parsed_raw
    elif BUDGET_WORD.search(raw_text):
        note = f"第{index}条金额原文是预算或限价，不计入中标金额"
    if amount is not None and amount <= 0:
        amount = None
        note = f"第{index}条金额不是正数，按未披露处理"
    return {
        "title": title,
        "url": url,
        "key": "u:" + canon_url(url) if canon_url(url) else "t:" + norm_text(title),
        "publish_date": day,
        "buyer": str(raw.get("buyer") or "").strip() or "未注明",
        "winner": str(raw.get("winner") or "").strip() or "未注明",
        "region": str(raw.get("region") or "").strip() or "未注明地区",
        "topic": str(raw.get("topic") or "").strip() or "未分类",
        "doc_type": doc_type,
        "amount": amount,
        "amount_raw": str(raw.get("amount_raw") or "").strip(),
        "source_name": str(raw.get("source_name") or "").strip(),
    }, note


def analyze(rows: list, since: datetime | None, until: datetime | None) -> tuple[str, int, list[str]]:
    warnings: list[str] = []
    kept: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            warnings.append(f"第{index}条不是对象，已丢弃")
            continue
        item, note = clean_row(raw, index)
        if note:
            warnings.append(note)
        if item is None:
            continue
        if since and item["publish_date"] < since:
            warnings.append(f"《{item['title']}》早于窗口，已丢弃")
            continue
        if until and item["publish_date"] > until:
            warnings.append(f"《{item['title']}》晚于窗口，已丢弃")
            continue
        if item["key"] in seen:
            warnings.append(f"《{item['title']}》与已有链接重复，已丢弃")
            continue
        seen.add(item["key"])
        kept.append(item)

    awards = [item for item in kept if item["doc_type"] in AWARDS]
    disclosed = [item for item in awards if item["amount"] is not None]
    lines = ["### 脚本统计", ""]
    lines.append(f"- 入选公告：{len(kept)} 条")
    lines.append(f"- 其中招标公告：{sum(item['doc_type'] == '招标公告' for item in kept)} 条")
    lines.append(f"- 其中采购意向：{sum(item['doc_type'] == '采购意向' for item in kept)} 条")
    lines.append(f"- 其中中标或成交公告：{len(awards)} 条")
    if awards:
        rate = len(disclosed) / len(awards) * 100
        lines.append(f"- 中标金额披露率：{rate:.1f}%（{len(disclosed)}/{len(awards)}）")
    else:
        lines.append("- 中标金额披露率：无可统计的中标或成交公告")
    lines.append("")
    lines.append("热点按主题（招标侧含招标、采购意向和候选人公示；中标侧含成交）：")
    lines.append("")
    lines.append("| 主题 | 招标侧 | 中标侧 | 已披露中标金额合计 |")
    lines.append("| --- | ---: | ---: | ---: |")
    topics = sorted({item["topic"] for item in kept})
    for topic in topics:
        group = [item for item in kept if item["topic"] == topic]
        tender_count = sum(item["doc_type"] not in AWARDS for item in group)
        award_count = sum(item["doc_type"] in AWARDS for item in group)
        total = sum(item["amount"] or 0 for item in group if item["doc_type"] in AWARDS and item["amount"])
        amount_text = fmt_yuan(total) if total else "0"
        lines.append(f"| {topic} | {tender_count} | {award_count} | {amount_text} |")
    lines.append("")
    lines.append("已披露中标金额分档（未披露不进入分档）：")
    lines.append("")
    lines.append("| 金额档 | 项目数 | 占已披露项目 |")
    lines.append("| --- | ---: | ---: |")
    for low, high, label in BINS:
        count = sum(low <= item["amount"] < high for item in disclosed)
        share = f"{count / len(disclosed) * 100:.1f}%" if disclosed else "0.0%"
        lines.append(f"| {label} | {count} | {share} |")
    undisclosed = len(awards) - len(disclosed)
    lines.append(f"| 金额未披露 | {undisclosed} | 不纳入分母 |")
    lines.append("")
    if disclosed:
        amounts = [item["amount"] for item in disclosed]
        lines.append(f"- 已披露金额合计：{fmt_yuan(sum(amounts))}")
        lines.append(f"- 已披露金额中位数：{fmt_yuan(median(amounts))}")
        lines.append(f"- 已披露金额平均数：{fmt_yuan(sum(amounts) / len(amounts))}")
    else:
        lines.append("- 已披露金额合计：无")
        lines.append("- 已披露金额中位数：无")
        lines.append("- 已披露金额平均数：无")
    lines.append("")
    lines.append("季度分布：")
    lines.append("")
    by_quarter: dict[str, int] = defaultdict(int)
    for item in kept:
        day = item["publish_date"]
        by_quarter[f"{day.year}Q{(day.month - 1) // 3 + 1}"] += 1
    for quarter in sorted(by_quarter):
        lines.append(f"- {quarter}：{by_quarter[quarter]} 条")
    if not by_quarter:
        lines.append("- 无")
    lines.append("")
    lines.append("地区分布（按公告数，前 8）：")
    lines.append("")
    by_region: dict[str, int] = defaultdict(int)
    for item in kept:
        by_region[item["region"]] += 1
    for region, count in sorted(by_region.items(), key=lambda pair: (-pair[1], pair[0]))[:8]:
        lines.append(f"- {region}：{count} 条")
    if not by_region:
        lines.append("- 无")
    lines.append("")
    lines.append("已披露金额最高的中标或成交（最多 10 条）：")
    lines.append("")
    top = sorted(disclosed, key=lambda item: item["amount"], reverse=True)[:10]
    if not top:
        lines.append("- 无")
    for item in top:
        day = item["publish_date"].strftime("%Y-%m-%d")
        lines.append(
            f"- {day}｜{fmt_yuan(item['amount'])}｜{item['buyer']}｜{item['title']}｜{item['url']}"
        )
    return "\n".join(lines) + "\n", (0 if kept else 2), warnings


def self_test() -> int:
    rows = [
        {
            "title": "甲ESG报告中标公告",
            "url": "https://www.example.com/a?utm_source=x",
            "publish_date": "2025-01-15",
            "buyer": "甲",
            "region": "北京",
            "topic": "ESG报告与评级",
            "doc_type": "中标公告",
            "amount_raw": "80万元",
            "include_reason": "采购内容包含ESG报告",
        },
        {
            "title": "甲ESG报告中标公告转载",
            "url": "https://example.com/a",
            "publish_date": "2025-01-16",
            "doc_type": "中标公告",
            "amount_cny": 800000,
            "include_reason": "ESG报告",
        },
        {
            "title": "乙碳核查成交公告",
            "url": "https://example.com/b",
            "publish_date": "2025-06-01",
            "buyer": "乙",
            "region": "上海",
            "topic": "碳核算与核查",
            "doc_type": "成交公告",
            "amount_cny": 120_000_000,
            "include_reason": "温室气体核查",
        },
        {
            "title": "丙双碳咨询招标公告",
            "url": "https://example.com/c",
            "publish_date": "2025-11-20",
            "region": "山西",
            "topic": "双碳规划咨询",
            "amount_raw": "预算30万元",
            "include_reason": "服务碳达峰方案",
        },
        {
            "title": "没有依据",
            "url": "https://example.com/d",
            "publish_date": "2025-11-20",
            "include_reason": "普通信息化",
        },
        {
            "title": "丁ESG信息披露中标公告",
            "url": "https://example.com/e",
            "publish_date": "2025-08-01",
            "buyer": "丁",
            "region": "广东",
            "topic": "环境信息披露系统",
            "doc_type": "中标公告",
            "amount_raw": "中标金额：50万元（预算100万元）",
            "include_reason": "建设环境信息披露系统",
        },
    ]
    text, code, warnings = analyze(rows, datetime(2024, 1, 1), datetime(2026, 1, 1))
    checks = [
        code == 0,
        "1.20亿元" in text,
        "50.00万元" in text,
        "100.00万元" not in text,
        "已披露金额中位数：80.00万元" in text,
        "入选公告：4 条" in text,
        "中标金额披露率：100.0%（3/3）" in text,
        any("预算或限价" in item for item in warnings),
        "2025Q1：1 条" in text,
        any("没有依据" in item for item in warnings),
        any("重复" in item for item in warnings),
    ]
    if not all(checks):
        print(text)
        print("\n".join(warnings))
        print(checks)
        return 1
    empty, empty_code, _ = analyze([], None, None)
    if empty_code != 2 or "入选公告：0 条" not in empty:
        print("empty sample failed")
        return 1
    print("OK")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--self-test":
        return self_test()
    parser = argparse.ArgumentParser(description="汇总 ESG 中标记录")
    parser.add_argument("records")
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--out")
    args = parser.parse_args(argv[1:])
    try:
        rows = load_rows(args.records)
        since = parse_day(args.since) if args.since else None
        until = parse_day(args.until) if args.until else None
        if args.since and since is None or args.until and until is None:
            print("日期必须是 YYYY-MM-DD", file=sys.stderr)
            return 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"无法读取记录：{exc}", file=sys.stderr)
        return 1
    text, code, warnings = analyze(rows, since, until)
    for item in warnings:
        print(item, file=sys.stderr)
    sys.stdout.write(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
