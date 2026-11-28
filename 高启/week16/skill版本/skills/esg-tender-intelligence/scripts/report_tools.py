"""为 ESG 投标情报报告计算统计窗口并核对来源编号。"""

import argparse
import calendar
import re
import sys
from datetime import date
from pathlib import Path

ID_PATTERN = re.compile(r"\b(S\d{2,})\b")
ENTRY_PATTERN = re.compile(r"(?m)^\s*-\s+\*\*\[?(S\d{2,})\]?\*\*")
HEADING_PATTERN = re.compile(r"(?m)^##\s+.*来源清单\s*$")


def get_review_window(end_text: str) -> tuple[str, str]:
    """返回截止日前两年的起始日及截止日，包含首尾日期。"""
    try:
        end_date = date.fromisoformat(end_text)
    except ValueError as error:
        raise ValueError("截止日期格式必须是 YYYY-MM-DD") from error
    try:
        start_date = end_date.replace(year=end_date.year - 2)
    except ValueError:  # 闰日回溯到平年的 2 月 28 日。
        start_date = end_date.replace(year=end_date.year - 2, day=28)
    return start_date.isoformat(), end_date.isoformat()


def validate_reference_map(text: str) -> list[str]:
    """核对正文引用与来源清单编号，并检查重复和闲置来源。"""
    heading = HEADING_PATTERN.search(text)
    if heading is None:
        return ["缺少来源清单二级标题"]
    used = set(ID_PATTERN.findall(text[: heading.start()]))
    entries = ENTRY_PATTERN.findall(text[heading.end() :])
    listed = set(entries)
    errors = [f"正文引用 {item}，但来源清单没有该条目" for item in sorted(used - listed)]
    errors += [f"来源 {item} 未被正文或状态说明引用" for item in sorted(listed - used)]
    errors += [f"来源清单编号 {item} 重复" for item in sorted({item for item in entries if entries.count(item) > 1})]
    if not entries:
        errors.append("来源清单中没有符合格式的来源条目")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="ESG 投标情报报告辅助工具")
    commands = parser.add_subparsers(dest="command", required=True)
    window = commands.add_parser("window", help="计算截止日前两年的中标统计窗口")
    window.add_argument("end_date", help="检索截止日期，格式 YYYY-MM-DD")
    check = commands.add_parser("check", help="检查报告引用编号与来源清单")
    check.add_argument("report", type=Path, help="Markdown 报告路径")
    args = parser.parse_args()

    if args.command == "window":
        try:
            start, end = get_review_window(args.end_date)
        except ValueError as error:
            parser.error(str(error))
        print(f"统计窗口（含首尾）：{start} 至 {end}")
        print(f"默认文件名：ESG投标情报_{end}.md")
        return 0

    try:
        text = args.report.read_text(encoding="utf-8")
    except OSError as error:
        print(f"无法读取报告：{error}", file=sys.stderr)
        return 2
    errors = validate_reference_map(text)
    if errors:
        for error in errors:
            print(f"检查未通过：{error}", file=sys.stderr)
        return 1
    print("引用检查通过：来源编号均已对应，且没有重复或闲置来源。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
