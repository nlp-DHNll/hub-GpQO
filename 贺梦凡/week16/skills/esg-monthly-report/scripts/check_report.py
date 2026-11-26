#!/usr/bin/env python3
"""Check an ESG monthly report for the structure this skill promises."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED = [
    "## 报告信息",
    "## 执行摘要",
    "## 一、ESG政策、评级与标准动态",
    "### 1.1 本窗口动态",
    "### 1.2 仍有效的框架",
    "### 1.3 对客户的影响",
    "## 二、行业新闻与最佳实践",
    "### 2.1 行业新闻",
    "### 2.2 最佳实践",
    "## 三、公司动态、ESG影响与对标行动",
    "### 3.1 客户公司动态及ESG影响",
    "### 3.2 建议",
    "### 3.3 对标企业ESG关键行动",
    "### 3.4 窗口外对标",
    "## 信息缺口与检索说明",
    "## 信源附录",
]

CONTENT_SECTIONS = [
    "## 一、ESG政策、评级与标准动态",
    "## 二、行业新闻与最佳实践",
    "## 三、公司动态、ESG影响与对标行动",
]

BANNED = ["TODO", "TBD", "待补充", "填写说明", "格式示例", "lorem", "据了解", "业内人士", "相关专家表示"]
BULLET = re.compile(r"^\s{0,3}(?:[-*]|\d+\.)\s+\S")
LINK = re.compile(r"https?://[^\s<>)\]]+")
ADVICE = re.compile(r"【(高|中|低)｜(短期|中期)】")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def section(text: str, heading: str) -> str | None:
    match = re.search(rf"^{re.escape(heading)}\s*$", text, re.M)
    if not match:
        return None
    level = len(heading.split()[0])
    rest = text[match.end() :]
    nxt = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def unique_links(text: str) -> list[str]:
    seen: list[str] = []
    for raw in LINK.findall(text):
        link = raw.rstrip(".,;，。；")
        if link not in seen:
            seen.append(link)
    return seen


def table_data_rows(text: str) -> int:
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if re.match(r"^\|\s*-+", stripped):
            continue
        if "对标企业" in stripped and "窗口内关键行动" in stripped:
            continue
        rows.append(stripped)
    return len(rows)


def problems_in(text: str) -> list[str]:
    found: list[str] = []
    for heading in REQUIRED:
        if re.search(rf"^{re.escape(heading)}\s*$", text, re.M) is None:
            found.append(f"缺少标题：{heading}")

    for word in BANNED:
        if word.lower() in text.lower():
            found.append(f"出现禁止字样：{word}")

    links = unique_links(text)
    if len(links) < 10:
        found.append(f"独立链接只有 {len(links)} 个，至少 10 个")

    for heading in CONTENT_SECTIONS:
        body = section(text, heading)
        if body is None:
            continue
        if len(unique_links(body)) < 2:
            found.append(f"{heading} 内的独立链接少于 2 个")

    info = section(text, "## 报告信息")
    if info is not None:
        if "信息窗口" not in info or not DATE.search(info):
            found.append("报告信息需要写出信息窗口和 YYYY-MM-DD 日期")

    summary = section(text, "## 执行摘要")
    if summary is not None:
        count = sum(1 for line in summary.splitlines() if BULLET.match(line))
        if count < 5 or count > 8:
            found.append(f"执行摘要有 {count} 条，需要 5 到 8 条")

    advice = section(text, "### 3.2 建议")
    if advice is not None and len(ADVICE.findall(advice)) < 3:
        found.append("建议少于 3 条，或没有使用【高｜短期】这种标记")

    peers = section(text, "### 3.3 对标企业ESG关键行动")
    if peers is not None and table_data_rows(peers) < 3:
        found.append("对标表数据行少于 3 行")

    gap = section(text, "## 信息缺口与检索说明")
    if gap is not None and "剔除" not in gap:
        found.append("信息缺口与检索说明需要写明剔除情况")

    return found


def check_file(path: Path) -> list[str]:
    if not path.is_file():
        return [f"找不到报告：{path}"]
    return problems_in(path.read_text(encoding="utf-8-sig"))


def self_test() -> int:
    good_link = "https://example.com/a{}"
    bullets = "\n".join(
        f"- 2099-01-0{i}｜示例事实｜含义｜[来源]({good_link.format(i)})" for i in range(1, 6)
    )
    body_links = "\n".join(
        f"- 2099-01-15｜事实｜含义｜[来源](https://example.com/b{i})" for i in range(1, 4)
    )
    advice = "\n".join(
        [
            "- 【高｜短期】董秘办在两周内核对样本。依据：2099-01-15 的事实。",
            "- 【中｜中期】安环部在本季度核对排放口径。依据：2099-01-15 的事实。",
            "- 【低｜中期】战略部跟踪同业做法。依据：2099-01-15 的事实。",
        ]
    )
    peers = "\n".join(
        [
            "| 对标企业 | 窗口内关键行动 | 日期 | 可核验证据 | 相对客户的启示 |",
            "| --- | --- | --- | --- | --- |",
            "| 甲 | 行动 | 2099-01-02 | [来源](https://example.com/p1) | 启示 |",
            "| 乙 | 窗口内未检索到可核实的ESG关键行动 |  | [来源](https://example.com/p2) |  |",
            "| 丙 | 行动 | 2099-01-03 | [来源](https://example.com/p3) | 启示 |",
        ]
    )
    good = f"""
# 示例 ESG月报（2099-01-01 至 2099-01-31）

## 报告信息

- 信息窗口：2099-01-01 至 2099-01-31

## 执行摘要

{bullets}

## 一、ESG政策、评级与标准动态

### 1.1 本窗口动态

{body_links}

### 1.2 仍有效的框架

本栏无条目。

### 1.3 对客户的影响

| 事项 | 适用性 | 时间要求 | 建议动作 | 来源 |
| --- | --- | --- | --- | --- |
| 事项 | 直接适用 | 本季 | 核对 | [来源](https://example.com/c1) |

## 二、行业新闻与最佳实践

### 2.1 行业新闻

{body_links}

### 2.2 最佳实践

{body_links}

## 三、公司动态、ESG影响与对标行动

### 3.1 客户公司动态及ESG影响

{body_links}

### 3.2 建议

{advice}

### 3.3 对标企业ESG关键行动

{peers}

### 3.4 窗口外对标

本栏无条目。

## 信息缺口与检索说明

- 候选 20，入选 8，剔除 12，主要因为宣传稿。

## 信源附录

| 序号 | 日期 | 标题 | 层级（A/B） | 链接 |
| --- | --- | --- | --- | --- |
| 1 | 2099-01-15 | 标题 | A | https://example.com/z |
"""
    bad_hits = problems_in(good)
    if bad_hits:
        print("self-test expected a valid report, got:")
        for item in bad_hits:
            print(f"- {item}")
        return 1
    bad = good.replace("## 执行摘要", "## 摘要")
    if not problems_in(bad):
        print("self-test failed to reject a report with a missing heading")
        return 1
    print("OK")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "--self-test":
        return self_test()
    if len(argv) != 2:
        print("用法：python check_report.py <报告.md>", file=sys.stderr)
        return 2
    found = check_file(Path(argv[1]))
    if found:
        print(f"未通过，{len(found)} 项：")
        for item in found:
            print(f"- {item}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
