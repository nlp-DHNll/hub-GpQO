"""命令行入口：``check`` 验收一个运行目录，``run`` 启动一次无头运行。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from esgtools.checker import Verdict, check_run
from esgtools.contract import TIER_NAMES, VERIFICATION_NAMES, Case, Mode, RuleSet, Version, rule_set_for
from esgtools.runner import (
    DEFAULT_ALLOWED_TOOLS,
    DEFAULT_DENIED_TOOLS,
    DEFAULT_PERMISSION_MODE,
    TOOLS_DIR,
    WEEK16_DIR,
    HeadlessBackend,
    LocalClaudeCli,
    PermissionMode,
    RunOutcome,
    RunSpec,
    run_headless,
    window_from,
)

_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
RUN_ID_HELP = "运行目录名；默认「开始时间_案例_版本[_运行模式]」，只允许字母、数字、点、下划线与连字符"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="esgtools", description="week16 工具：验收器与无头运行器")
    commands = parser.add_subparsers(dest="command", required=True, metavar="{check,run}")

    check = commands.add_parser("check", help="验收一个运行目录：给出通过/不通过、逐条原因与度量")
    check.add_argument("run_dir", type=Path, help="运行目录")
    check.add_argument("--json", action="store_true", help="以 JSON 输出判定，供脚本使用")

    run = commands.add_parser("run", help="启动无头子会话执行任务，并把产物归入新的运行目录")
    run.add_argument("--case", required=True, choices=[case.value for case in Case], help="案例")
    run.add_argument(
        "--mode",
        choices=[mode.value for mode in Mode],
        help="运行模式；月报默认 report，招投标情报必填 summary 或 monitor",
    )
    run.add_argument(
        "--version",
        required=True,
        choices=[version.value for version in Version],
        help="无脚本版 noscript / 脚本版 scripted",
    )
    run.add_argument(
        "--skill", required=True, metavar="名@版本", help="skill 版本标识，如 esg-monthly-report@0.1.0"
    )
    run.add_argument("--task", required=True, help="交给子会话的一句话任务")
    run.add_argument("--client", help="客户；月报必填")
    run.add_argument("--industry", help="行业；月报必填")
    window = run.add_argument_group(
        "时间窗", "三种给法任选其一：--start [--end]、--days 或 --months；都不给就报错"
    )
    window.add_argument(
        "--start", type=date.fromisoformat, help="起始日期 YYYY-MM-DD；不给 --end 时结束日期取今天"
    )
    window.add_argument("--end", type=date.fromisoformat, help="结束日期 YYYY-MM-DD，须与 --start 成对给出")
    window.add_argument("--days", type=int, help="到今天为止往前取的天数（含今天）")
    window.add_argument("--months", type=int, help="到今天为止往前取的月数")
    run.add_argument(
        "--out-root", type=Path, default=WEEK16_DIR / "runs", help="运行目录的根，默认 week16/runs"
    )
    run.add_argument("--run-id", help=RUN_ID_HELP)
    run.add_argument("--workdir", type=Path, default=WEEK16_DIR, help="子会话的工作目录，默认 week16")
    run.add_argument(
        "--allow",
        default="",
        help="在默认白名单上追加的工具，逗号分隔（如脚本版的 Bash、子代理）",
    )
    run.add_argument(
        "--deny",
        default="",
        help="在默认禁用项上追加的工具或路径，逗号分隔；默认已禁用 WebFetch、记忆目录与 .scratch/",
    )
    run.add_argument(
        "--permission-mode",
        choices=[mode.value for mode in PermissionMode],
        default=DEFAULT_PERMISSION_MODE.value,
        help="权限模式；默认 dontAsk（不询问，白名单外一律拒绝）。本机默认的 auto 模式会放行白名单外的命令",
    )
    run.add_argument("--model", help="子会话的模型；不填用本机默认")
    run.add_argument("--timeout", type=float, default=3600.0, help="子会话最长运行秒数，默认 3600")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    backend: HeadlessBackend | None = None,
    now: datetime | None = None,
) -> int:
    """命令行入口。返回退出码：0 通过 / 运行成立，1 不通过 / 运行失败，2 参数有误。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args)
    return _run(parser, args, backend=backend or LocalClaudeCli(), now=now or datetime.now().astimezone())


# ---- check ----


def _check(args: argparse.Namespace) -> int:
    verdict = check_run(args.run_dir)
    if args.json:
        print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_verdict(verdict))
    return 0 if verdict.passed else 1


_LABELS: dict[str, str] = {
    "evidence_total": "证据条数",
    "qualified_sources": "合格来源数",
    "verification_distribution": "核实状态",
    "credibility_tier_distribution": "可信度分级",
    "date_in_window": "日期落窗",
    "citations": "角标",
    "body_chars": "正文字数",
    "records_total": "招标记录",
    "in_scope_total": "范围内",
    "out_of_scope_total": "边界外",
    "sample_size": "样本量（范围内中标公告）",
    "in_scope_tender_count": "范围内招标公告",
    "amount_available": "取到金额",
    "amount_rate": "金额可得率",
    "source_sites": "来源站点",
    "topics": "主题",
    "record_count": "新增招标",
    "seen_before_count": "运行前已见",
    "baseline": "基线",
    "latest_published_at": "最晚发布日期",
    "cost": "成本耗时",
}

_VALUE_NAMES: dict[str, str] = {str(tier): name for tier, name in TIER_NAMES.items()} | {
    member.value: name for member, name in VERIFICATION_NAMES.items()
}
"""度量分布里的取值（可信度分级、核实状态）显示成中文叫法。"""


def render_verdict(verdict: Verdict) -> str:
    """给人看的判定：结论、逐条规则、度量。"""
    failed = [check for check in verdict.checks if not check.passed]
    if verdict.passed:
        conclusion = "通过"
    else:
        conclusion = f"不通过（{len(failed)}/{len(verdict.checks)} 条规则不通过）"
    lines = [
        f"运行目录：{verdict.run_dir}",
        f"规则集：{verdict.rule_set or '认不出（运行记录缺失，或案例与运行模式不合法）'}",
        f"结论：{conclusion}",
        "",
    ]
    for check in verdict.checks:
        lines.append(f"  {'✔' if check.passed else '✘'} {check.rule:<26} {check.title}")
        if not check.passed:
            lines += [f"        - {reason}" for reason in check.detail.split("；") if reason]
    if verdict.metrics:
        lines += ["", "度量："] + [f"  {line}" for line in render_metrics(verdict.metrics)]
    return "\n".join(lines)


def render_metrics(metrics: dict[str, Any]) -> list[str]:
    """把度量渲染成一行一项；成本耗时放最后。"""
    items = [(key, value) for key, value in metrics.items() if key != "cost"]
    if "cost" in metrics:
        items.append(("cost", metrics["cost"]))
    lines = []
    for key, value in items:
        label = _LABELS.get(key, key)
        if key == "cost":
            lines.append(f"{label}：{_render_cost(value)}")
        elif key == "date_in_window":
            lines.append(f"{label}：{_render_date_window(value)}")
        elif key.endswith("rate") and isinstance(value, (int, float)):
            lines.append(f"{label}：{_percent(value)}")
        else:
            lines.append(f"{label}：{_render_value(value)}")
    return lines


def _render_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        # 费用要精确到子会话输出的六位小数，不能在这里截断。
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, dict):
        if not value:
            return "无"
        return "，".join(
            f"{_VALUE_NAMES.get(str(key), key)}={_render_value(item)}" for key, item in value.items()
        )
    if isinstance(value, list):
        return "、".join(_render_value(item) for item in value)
    return str(value)


def _percent(rate: float) -> str:
    """比率写成百分数：整数百分比不带小数，其余保留一位。"""
    return f"{rate * 100:.1f}".rstrip("0").rstrip(".") + "%"


def _render_date_window(window: Any) -> str:
    if not isinstance(window, dict) or not window.get("denominator"):
        return "—"
    rate = window.get("rate")
    percent = _percent(rate) if isinstance(rate, (int, float)) else "—"
    return (
        f"{percent}（{window['in_window']}/{window['denominator']}；"
        f"窗外 {window['out_of_window']}，日期未知 {window['unknown']}）"
    )


def _render_cost(cost: Any) -> str:
    if not isinstance(cost, dict):
        return "—"
    return " ｜ ".join(
        f"{label} {_render_value(cost.get(key))}"
        for key, label in (
            ("duration_ms", "耗时（毫秒）"),
            ("input_tokens", "输入 token"),
            ("output_tokens", "输出 token"),
            ("cost_usd", "费用（美元）"),
            ("search_count", "搜索次数"),
        )
    )


# ---- run ----


def _appended(defaults: tuple[str, ...], extra: str) -> tuple[str, ...]:
    """默认名单加上命令行追加的项，去重并保持先后。"""
    return tuple(dict.fromkeys((*defaults, *(tool.strip() for tool in extra.split(",") if tool.strip()))))


def _run(
    parser: argparse.ArgumentParser, args: argparse.Namespace, *, backend: HeadlessBackend, now: datetime
) -> int:
    if args.run_id is not None and _RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        parser.error(f"--run-id {RUN_ID_HELP}")

    case = Case(args.case)
    mode = Mode(args.mode) if args.mode else (Mode.REPORT if case is Case.MONTHLY_REPORT else None)
    if mode is None:
        parser.error("招投标情报须用 --mode 指定运行模式：summary（汇总）或 monitor（监控）")
    if case is Case.MONTHLY_REPORT and not (args.client and args.industry):
        parser.error("月报须用 --client 与 --industry 给出客户与行业")
    try:
        start, end = window_from(
            today=now.date(), start=args.start, end=args.end, days=args.days, months=args.months
        )
        spec = RunSpec(
            case=case,
            mode=mode,
            version=Version(args.version),
            skill_version=args.skill,
            task=args.task,
            window_start=start,
            window_end=end,
            client=args.client,
            industry=args.industry,
            allowed_tools=_appended(DEFAULT_ALLOWED_TOOLS, args.allow),
            denied_tools=_appended(DEFAULT_DENIED_TOOLS, args.deny),
            permission_mode=PermissionMode(args.permission_mode),
            model=args.model,
            timeout_seconds=args.timeout,
        )
    except ValueError as exc:
        parser.error(str(exc))
    outcome = run_headless(
        spec,
        backend,
        workdir=args.workdir,
        out_root=args.out_root,
        now=now,
        run_id=args.run_id,
    )
    print(render_outcome(outcome, rule_set=rule_set_for(spec.case, spec.mode)))
    return 0 if outcome.ok else 1


def render_outcome(outcome: RunOutcome, *, rule_set: RuleSet | None) -> str:
    """运行结束后给人看的说明：运行目录、提示、可直接复制执行的验收命令。"""
    lines = [
        f"运行{'成立' if outcome.ok else '失败'}：{outcome.run_dir}",
        f"接下来验收：cd {TOOLS_DIR} && {sys.executable} -m esgtools check {outcome.run_dir}",
    ]
    if rule_set is RuleSet.DAILY:
        lines.append(
            "监控模式：验收器按运行目录里的 seen_before.json（运行前已见清单快照）判定去重，"
            "缺少它 daily.seen 规则不通过"
        )
    lines += [f"警告：{warning}" for warning in outcome.warnings]
    lines += [f"问题：{problem}" for problem in outcome.problems]
    return "\n".join(lines)
