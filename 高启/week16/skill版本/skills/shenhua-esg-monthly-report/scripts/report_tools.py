"""为中国神华 ESG 月报提供轻量的日期和引用编号检查。"""

import argparse
import calendar
import re
import sys
from pathlib import Path


SOURCE_ID_PATTERN = re.compile(r"\[(S\d{2,})\]")
SOURCE_ENTRY_PATTERN = re.compile(r"(?m)^\s*-\s+\*\*\[(S\d{2,})\]\*\*")
SOURCE_HEADING_PATTERN = re.compile(r"(?m)^##\s+(?:(?:[一二三四五六七八九十]+|\d+)[、.]\s*)?来源清单\s*$")


def get_month_range(month_text: str) -> tuple[str, str]:
    """返回 YYYY-MM 对应的首日和末日，并拒绝格式错误的月份。"""
    if not re.fullmatch(r"\d{4}-\d{2}", month_text):
        raise ValueError("月份格式必须是 YYYY-MM，例如 2026-05")

    year, month = map(int, month_text.split("-"))
    if not 1 <= month <= 12:
        raise ValueError("月份中的月份部分必须在 01 到 12 之间")

    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def validate_reference_map(report_text: str) -> list[str]:
    """检查正文引用与“来源清单”中的来源编号是否一一对应。"""
    heading = SOURCE_HEADING_PATTERN.search(report_text)
    if heading is None:
        return ["缺少二级标题“## 来源清单”"]

    report_body = report_text[: heading.start()]
    source_section = report_text[heading.end() :]
    cited_ids = set(SOURCE_ID_PATTERN.findall(report_body))
    listed_ids = SOURCE_ENTRY_PATTERN.findall(source_section)
    listed_set = set(listed_ids)
    errors: list[str] = []

    if not listed_ids:
        errors.append("来源清单中没有符合格式的来源条目（示例：- **[S01]** 标题）")

    for source_id in sorted(cited_ids - listed_set):
        errors.append(f"正文或资料状态中引用了 {source_id}，但来源清单中没有对应条目")
    for source_id in sorted(listed_set - cited_ids):
        errors.append(f"来源清单中的 {source_id} 未被引用（正文或资料状态中没有此编号）")

    seen: set[str] = set()
    for source_id in listed_ids:
        if source_id in seen:
            errors.append(f"来源清单中的 {source_id} 条目重复")
        seen.add(source_id)

    return errors


def main() -> int:
    """解析工具命令并输出日期范围或引用核查结果。"""
    parser = argparse.ArgumentParser(description="中国神华 ESG 月报辅助工具")
    commands = parser.add_subparsers(dest="command", required=True)

    period_parser = commands.add_parser("period", help="计算目标月份的起止日期和默认文件名")
    period_parser.add_argument("month", help="目标月份，格式 YYYY-MM")

    check_parser = commands.add_parser("check", help="核对报告引用编号与来源清单")
    check_parser.add_argument("report", type=Path, help="Markdown 报告路径")

    args = parser.parse_args()
    if args.command == "period":
        try:
            start_date, end_date = get_month_range(args.month)
        except ValueError as error:
            parser.error(str(error))
        print(f"目标月份：{args.month}")
        print(f"检索日期范围：{start_date} 至 {end_date}")
        print(f"默认文件名：中国神华_ESG月报_{args.month}.md")
        return 0

    try:
        report_text = args.report.read_text(encoding="utf-8")
    except OSError as error:
        print(f"无法读取报告：{error}", file=sys.stderr)
        return 2

    errors = validate_reference_map(report_text)
    if errors:
        for error in errors:
            print(f"检查未通过：{error}", file=sys.stderr)
        return 1

    heading = SOURCE_HEADING_PATTERN.search(report_text)
    assert heading is not None  # 前面的校验已确认标题存在。
    cited_ids = set(SOURCE_ID_PATTERN.findall(report_text[: heading.start()]))
    print(f"引用检查通过：{len(cited_ids)} 个来源编号均有对应条目，且没有未引用来源。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
