#!/usr/bin/env python3
"""Search a fixed query list and write an extractive ESG evidence digest."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_lib"))
from web_collect import collect, self_test  # noqa: E402

DEFAULT_QUERIES = [
    "2026年10月 中国神华 ESG OR 可持续发展",
    "2026年10月 上海证券交易所 可持续发展报告",
    "2026年10月 生态环境部 碳市场",
    "2026年10月 煤炭 绿色矿山 OR 煤电 低碳",
    "2026年10月 中煤能源 ESG OR 陕西煤业 环境",
    "中国神华 2026年10月 公告",
]


def parse_day(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def render_markdown(result: dict, client: str, since: str, until: str) -> str:
    kept = [item for item in result["items"] if item["kept"]]
    lines = [
        f"# {client} 抽取式证据（{since} 至 {until}）",
        "",
        "这些句子是从已打开页面原文截取的，脚本没有改写。含义和建议不在本文件里。",
        "",
        f"- 查询 {len(result['queries'])} 条，命中 {result['hit_count']} 条，去重后 {result['unique_count']} 条",
        f"- 打开页面 {result['opened_count']} 个，入选 {len(kept)} 条，耗时 {result['elapsed_sec']} 秒",
        "",
    ]
    if not kept:
        lines.append("入选为空。下面保留未入选原因，方便补查，不能把这些句子写成已核实事实。")
        lines.append("")
    for item in result["items"]:
        mark = "入选" if item["kept"] else "未入选"
        scores = item["scores"]
        lines.append(f"## [{mark}] {item['title']}")
        lines.append("")
        lines.append(
            f"- 层级 {item['tier']}｜日期判断 {item['date_status']}｜已打开 {item['opened']}｜"
            f"总分 {scores['总分']}（权威{scores['权威']} 相关{scores['相关']} 新颖{scores['新颖']} "
            f"重大{scores['重大']} 可行动{scores['可行动']}）"
        )
        lines.append(f"- 链接：{item['url']}")
        if item.get("excerpt"):
            lines.append(f"- 原文摘句：{item['excerpt']}")
        elif item.get("snippet"):
            lines.append(f"- 仅搜索摘要，未当事实：{item['snippet']}")
        lines.append("")
    if result["errors"]:
        lines.append("## 检索失败")
        lines.append("")
        for error in result["errors"]:
            lines.append(f"- {error}")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    parser = argparse.ArgumentParser(description="ESG 月报的确定性检索与抽取式摘要")
    parser.add_argument("--client", default="中国神华")
    parser.add_argument("--since", default="2026-10-01")
    parser.add_argument("--until", default="2026-10-31")
    parser.add_argument("--per-query", type=int, default=4)
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--deadline", type=float, default=90)
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--url", action="append", dest="urls", help="跳过搜索，只打开这些地址并抽取")
    parser.add_argument("--out", required=True, help="JSON 输出路径，同名 .md 会一起写出")
    args = parser.parse_args(argv[1:])
    queries = args.queries or DEFAULT_QUERIES
    result = collect(
        queries,
        parse_day(args.since),
        parse_day(args.until),
        (args.client, "神华", "601088"),
        per_query=args.per_query,
        max_pages=max(args.max_pages, len(args.urls or [])),
        timeout=args.timeout,
        deadline_sec=args.deadline,
        seed_urls=args.urls,
    )
    result["arm"] = "script"
    result["client"] = args.client
    result["since"] = args.since
    result["until"] = args.until
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    out.with_suffix(".md").write_text(
        render_markdown(result, args.client, args.since, args.until),
        encoding="utf-8",
    )
    kept = sum(1 for item in result["items"] if item["kept"])
    print(f"命中 {result['hit_count']}，打开 {result['opened_count']}，入选 {kept}，用时 {result['elapsed_sec']}s")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
