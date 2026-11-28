#!/usr/bin/env python
"""把若干运行目录、盲评结果、可溯源率结果各汇成一张 Markdown 表（对比实验的表格由它生成）。

python summarize_runs.py ../runs/<运行目录>...                      # 验收结论与成本耗时
python summarize_runs.py --judge ../对比/judge-monthly.json        # LLM 盲评
python summarize_runs.py --trace  ../对比/trace-monthly.json ...   # 可溯源率
"""

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from esgtools.checker import check_run  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    try:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded


def _percent(rate: object) -> str:
    return f"{rate:.1%}" if isinstance(rate, (int, float)) else "—"


def headline(rule_set: str | None, metrics: dict[str, Any]) -> str:
    """按规则集挑出最说明问题的几个度量。"""
    if rule_set == "monthly":
        window = metrics.get("date_in_window", {})
        return (
            f"证据 {metrics.get('evidence_total')}，合格来源 {metrics.get('qualified_sources')}，"
            f"日期落窗 {_percent(window.get('rate'))}，正文 {metrics.get('body_chars')} 字"
        )
    if rule_set == "summary":
        return (
            f"记录 {metrics.get('records_total')}，样本 {metrics.get('sample_size')}，"
            f"金额可得率 {_percent(metrics.get('amount_rate'))}"
        )
    if rule_set == "daily":
        return f"新增 {metrics.get('record_count')}，运行前已见 {metrics.get('seen_before_count')}"
    return "—"


def run_row(run_dir: Path) -> str:
    verdict = check_run(run_dir)
    record = _load(run_dir / "run.json")
    minutes, cost = record.get("duration_ms"), record.get("cost_usd")
    failed = [check.rule for check in verdict.checks if not check.passed]
    searches = record.get("search_count") or "—"
    if (run_dir / "script_usage.json").is_file():  # 脚本版：搜索发生在脚本里，运行器数不到
        usage = _load(run_dir / "script_usage.json").get("searches", {})
        searches = " + ".join(
            f"{name} {entry.get('ok', 0)}" for name, entry in usage.items() if entry.get("ok")
        )
    return " | ".join(
        [
            run_dir.name,
            f"{record.get('version', '—')} / {record.get('invocation', '—')}",
            "通过" if verdict.passed else "不通过（" + "、".join(failed) + "）",
            headline(verdict.rule_set.value if verdict.rule_set else None, verdict.metrics),
            str(searches),
            f"{minutes / 60000:.1f}" if minutes else "—",
            f"{cost:.2f}" if isinstance(cost, (int, float)) else "—",
        ]
    )


RUN_HEAD = (
    "| 运行目录 | 版本 / 运行方式 | 验收 | 关键度量 | 搜索次数 | 耗时（分） | 费用（美元） |\n"
    "|---|---|---|---|---|---|---|"
)


def judge_table(path: Path) -> str:
    result = _load(path)
    first, second = result.get("a", {}), result.get("b", {})
    names = [Path(side.get("run_dir", "")).name for side in (first, second)]
    lines = [f"| 维度 | {names[0]} | {names[1]} |", "|---|---|---|"]
    for dimension, scores in first.get("scores", {}).items():
        other = second.get("scores", {}).get(dimension, {})
        lines.append(f"| {dimension} | {scores.get('mean')} | {other.get('mean')} |")
    lines.append(f"| **总分** | **{first.get('total')}** | **{second.get('total')}** |")
    return "\n".join(lines)


def trace_table(path: Path) -> str:
    lines = [
        "| 运行目录 | 核验条数 | 来源可达率 | 日期落窗率（日期未知） | 原文支持率 | 可溯源率 |",
        "|---|---|---|---|---|---|",
    ]
    for run in _load(path).get("runs", []):
        counts, rates = run.get("counts", {}), run.get("rates", {})
        lines.append(
            f"| {Path(run.get('run_dir', '')).name} | {counts.get('checked')} | {_percent(rates.get('reachable_rate'))} | "  # noqa: E501
            f"{_percent(rates.get('in_window_rate'))}（{counts.get('unknown_date')}） | "
            f"{_percent(rates.get('support_rate'))} | {_percent(rates.get('traceable_rate'))} |"
        )
    return "\n".join(lines)


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args[0] == "--judge":
        print(judge_table(Path(args[1])))
    elif args[0] == "--trace":
        print("\n\n".join(trace_table(Path(name)) for name in args[1:]))
    else:
        print(RUN_HEAD)
        for name in args:
            print(run_row(Path(name).expanduser().resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
