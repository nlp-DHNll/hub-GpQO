"""中国神华 ESG 月报 Agent 的命令行入口。"""

import argparse
import re
import sys
from datetime import date, datetime, timedelta

from backend.config import DEFAULT_REPORT_DIR, REPORT_TIMEZONE
from backend.data_models import RunEvent, RunResult
from backend.enums import RunStatus, StepName
from backend.errors import RunFailure
from backend.offline import OFFLINE_STEPS
from backend.workflow import run_agent

COMPANY = "中国神华"
STEP_LABELS = {
    StepName.SEARCH: "搜索资料",
    StepName.FILTER_SOURCES: "筛选资料",
    StepName.GENERATE_REPORT: "生成初稿",
    StepName.EVALUATE_CONTENT: "评价内容",
    StepName.REVISE_REPORT: "调整报告",
    StepName.EVALUATE_READABILITY: "评价可读性",
    StepName.SAVE_REPORT: "保存报告",
    StepName.SAVE_SOURCE_LIST: "保存资料清单",
}


def resolve_month(value: str | None, *, today: date) -> str:
    """校验报告月份，未指定时取上一个完整自然月。"""
    current_month = today.replace(day=1)
    if value is None:
        return (current_month - timedelta(days=1)).isoformat()[:7]

    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("月份格式应为 YYYY-MM，例如 2026-10")

    try:
        requested_month = date.fromisoformat(f"{value}-01")
    except ValueError as error:
        raise ValueError("请输入有效的报告月份，例如 2026-10") from error

    if requested_month >= current_month:
        raise ValueError("报告月份必须是已结束的自然月")
    return value


def show_progress(event: RunEvent) -> None:
    """把运行日志中的步骤事件显示为命令行进度。"""
    step = event.state.step
    if step is None:
        return
    label = STEP_LABELS[step.name]
    if step.attempt == 2:
        label += "（补搜）"
    if event.state.repair_round:
        label += f"（已用修正 {event.state.repair_round} 轮）"
    if event.event == "step_started":
        print(f"开始：{label}")
    elif event.event == "review_result":
        print(f"{label}：{'通过' if event.details['passed'] else '待调整'}")
    elif event.event == "model_output_truncated" and "next_max_tokens" in event.details:
        print(f"{label}：输出被截断，正在扩大输出预算重试一次")
    elif event.event == "step_completed":
        print(f"完成：{label}，耗时 {step.duration_ms} ms")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析命令行参数，并将月份转换成已校验的 YYYY-MM 字符串。"""
    parser = argparse.ArgumentParser(description=f"{COMPANY} ESG 月报 Agent")
    parser.add_argument(
        "month",
        nargs="?",
        metavar="YYYY-MM",
        help="报告月份，省略时取上一个完整自然月",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="用合成资料离线演示 Agent 流程")
    mode.add_argument("--sources-only", action="store_true", help="搜索并保存已核验的原文资料清单")
    args = parser.parse_args(argv)
    try:
        args.month = resolve_month(args.month, today=datetime.now(REPORT_TIMEZONE).date())
    except ValueError as error:
        parser.error(str(error))
    return args


def _run_selected_mode(month: str, *, offline: bool, sources_only: bool) -> RunResult:
    """按命令行参数启动离线演示、资料核验或完整月报。"""
    if offline:
        print("运行模式：离线演示")
        return run_agent(
            month,
            OFFLINE_STEPS,
            reports_dir=DEFAULT_REPORT_DIR / "offline",
            on_event=show_progress,
        )

    from backend.runtime import run_live_report, run_live_source_check

    if sources_only:
        print("运行模式：资料核验")
        return run_live_source_check(month, show_progress)
    print("运行模式：生成月报")
    return run_live_report(month, show_progress)


def _show_result(result: RunResult, *, sources_only: bool) -> int:
    """显示输出路径或失败原因，并返回对应的进程退出码。"""
    print(f"日志路径：{result.log_path}")
    if result.state.status is RunStatus.SUCCEEDED:
        label = "资料清单" if sources_only else "报告"
        print(f"{label}路径：{result.report_path}")
        return 0
    step = result.state.step
    stage = STEP_LABELS[step.name] if step is not None else "初始化"
    print(f"{stage}：{result.message}", file=sys.stderr)
    return 130 if result.state.status is RunStatus.CANCELLED else 1


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    print(f"报告企业：{COMPANY}")
    print(f"报告月份：{args.month}")
    try:
        result = _run_selected_mode(args.month, offline=args.offline, sources_only=args.sources_only)
    except RunFailure as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError as error:
        print(f"无法写入运行日志：{error}", file=sys.stderr)
        return 1
    return _show_result(result, sources_only=args.sources_only)


if __name__ == "__main__":
    raise SystemExit(main())
