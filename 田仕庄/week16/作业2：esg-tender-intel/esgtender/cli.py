"""命令行入口：解析参数、打印摘要、决定退出码。

编排在 pipeline.py。这个文件只做三件事：把 argv 变成 Namespace、把
``RunSummary`` 打印成人能读的样子、把结果翻译成退出码。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import pipeline
from . import render as render_mod

SKILL_ROOT = Path(__file__).resolve().parents[1]


def print_summary(summary: dict, report_paths: list[Path], records: list[dict]) -> None:
    print("== ESG 招标情报 ==")
    windows = summary.get("freshness_windows") or []
    if len(windows) > 1:
        window_note = f" | 分 {len(windows)} 段检索（{windows[-1].split('..')[0]} 起）"
    else:
        window_note = ""
    print(
        f"窗口 {summary['days']} 天 | provider={summary['provider']} | "
        f"query {len(summary['queries'])} 条{window_note}"
    )
    if summary.get("preset"):
        print(f"行业预设：{summary['preset']}")
    shown_note = (
        f"，清单展示前 {summary['shown']} 条" if summary.get("shown", 0) < summary["kept"] else ""
    )
    window_note2 = ""
    if summary.get("window_total") and summary["window_total"] != summary["kept"]:
        window_note2 = f"（窗口内共 {summary['window_total']} 条，本次只输出新增）"
    drops = [
        f"业务重复 {summary['duplicates']}",
        f"低于阈值 {summary['below_threshold']}",
        f"非采购剔除 {summary.get('not_tender', 0)}",
    ]
    # --stage 过滤曾经只在 HTML 里体现：命令行摘要显示「保留 0 条」，
    # 看着像检索失败，其实是被阶段条件筛掉了。
    if summary.get("stage_filtered"):
        drops.append(f"阶段筛除 {summary['stage_filtered']}")
    print(
        f"原始命中 {summary['raw_hits_total']} 次 → {summary['raw_hits']} 个不同页面"
        f" → 保留 {summary['kept']} 条{window_note2}{shown_note}"
        f"（{' / '.join(drops)}）"
    )
    if summary.get("new") is not None:
        print(f"增量：本期新增 {summary['new']} 条，往期已见 {summary['window_total'] - summary['new']} 条")
    stages = summary.get("stages") or []
    if stages:
        print("阶段：" + " | ".join(f"{item['label']} {item['count']}" for item in stages))
    if summary.get("award_links"):
        print(f"招标—中标关联：{summary['award_links']} 组")
    if summary["failures"]:
        print(f"失败 query {len(summary['failures'])} 条：")
        for failure in summary["failures"]:
            print(f"  - {failure['query']}: {failure['reason']}")
    print(f"报告：{report_paths[0]}")
    for extra in report_paths[1:]:
        print(f"      {extra}")
    if records:
        print("前 5 条：")
        for index, record in enumerate(records[:5], start=1):
            title = record["raw"].get("title_clean") or record["raw"]["title"]
            amount = render_mod.fmt_amount(record["fields"]["amount_cny"])
            stage = (record.get("stage") or {}).get("label") or "—"
            print(
                f"  {index}. [{record['track']['relevance']:.2f}] {title[:48]}"
                f" | {record['fields']['buyer']['value'] or 'N/A'} | {amount} | {stage}"
            )



def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="检索 ESG / 双碳 / 碳资产相关招标公告，输出结构化清单报告。"
    )
    parser.add_argument("--query", "-q", help="自定义关键词，逗号分隔；缺省按 scope.yaml 自动组合")
    parser.add_argument("--days", type=int, default=30, help="回溯天数，默认 30")
    parser.add_argument("--provider", choices=["bocha", "fixture"], help="覆盖 scope.yaml 的 provider")
    parser.add_argument("--count", type=int, help="单次检索条数（博查上限 50）")
    parser.add_argument("--max-queries", type=int, help="最多发出的 query 条数")
    parser.add_argument("--limit", type=int, default=50, help="报告最多输出条数，默认 50")
    parser.add_argument(
        "--format",
        choices=["html", "md", "docx", "both", "all"],
        default="html",
        help="报告格式：html（默认）/ md / docx；both=html+md，all=三种都写",
    )
    parser.add_argument("--min-relevance", type=float, help="覆盖赛道阈值，只保留不低于该值的记录")
    parser.add_argument(
        "--stage",
        choices=["tender", "award", "change", "other"],
        help="只保留某一公告阶段：tender=招标中，award=已中标成交",
    )
    parser.add_argument("--preset", help="行业预设名（config/presets/*.yaml），如 energy")
    parser.add_argument("--list-presets", action="store_true", help="列出可用行业预设后退出")
    parser.add_argument(
        "--sources",
        action="store_true",
        help="按 config/sources.yaml 追加 site: 定向 query 与列表页抓取（默认关闭，会增加请求数）",
    )
    parser.add_argument("--sources-config", help="指定 sources.yaml 路径")
    parser.add_argument("--max-site-queries", type=int, help="覆盖 sources.yaml 的 max_site_queries")
    parser.add_argument(
        "--incremental", action="store_true", help="读写已推送库，标注本期新增/往期已见"
    )
    parser.add_argument(
        "--only-new", action="store_true", help="报告只保留本期新增（隐含 --incremental）"
    )
    parser.add_argument("--db", help="已推送库路径，默认 data/tenders.db")
    parser.add_argument("--no-store", action="store_true", help="完全不碰已推送库")
    parser.add_argument("--prune-days", type=int, help="清理 N 天未再出现的库内记录")
    parser.add_argument(
        "--notify", choices=["webhook", "email"], help="报告生成后推送（密钥只从环境变量读）"
    )
    parser.add_argument("--notify-dry-run", action="store_true", help="只打印推送内容，不实际发送")
    parser.add_argument("--out", default=str(SKILL_ROOT / "output"), help="输出根目录")
    parser.add_argument("--scope", help="指定 scope.yaml 路径")
    parser.add_argument("--no-cache", action="store_true", help="忽略检索缓存，强制重新请求")
    parser.add_argument("--print-json", action="store_true", help="额外输出机器可读摘要")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析 → 执行 → 打印 → 退出码。"""
    args = parse_args(argv)
    outcome = pipeline.execute(args)
    if isinstance(outcome, int):  # 配置类错误，execute 已把原因写到 stderr
        return outcome
    print_summary(outcome.summary, outcome.report_paths, outcome.shown)
    if args.print_json:
        print(json.dumps(outcome.summary, ensure_ascii=False))
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
