#!/usr/bin/env python3
"""Check the two-year ESG bid report or a daily tender push."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DIGEST_REQUIRED = [
    "## 报告信息",
    "## 执行摘要",
    "## 一、口径与样本",
    "## 二、热点招标主题",
    "## 三、中标金额分布",
    "### 脚本统计",
    "### 怎么读这些数字",
    "## 四、结构观察",
    "## 五、对业务的含义",
    "## 信息缺口与检索说明",
    "## 信源与明细附录",
]
BANNED = ["TODO", "TBD", "待补充", "填写说明", "lorem", "据了解", "业内人士"]
BULLET = re.compile(r"^\s{0,3}(?:[-*]|\d+\.)\s+\S")
LINK = re.compile(r"https?://[^\s<>)\]]+")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
SAMPLE_SENTENCE = "本报告是公开网络样本，不是全国招标全量统计"


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


def digest_problems(text: str) -> list[str]:
    found: list[str] = []
    for heading in DIGEST_REQUIRED:
        if re.search(rf"^{re.escape(heading)}\s*$", text, re.M) is None:
            found.append(f"缺少标题：{heading}")
    for word in BANNED:
        if word.lower() in text.lower():
            found.append(f"出现禁止字样：{word}")
    if SAMPLE_SENTENCE not in text:
        found.append("缺少公开样本声明")
    if "披露率" not in text:
        found.append("脚本统计需要保留披露率")
    links = unique_links(text)
    if len(links) < 8:
        found.append(f"独立链接只有 {len(links)} 个，至少 8 个")
    info = section(text, "## 报告信息")
    if info is not None and ("信息窗口" not in info or not DATE.search(info)):
        found.append("报告信息需要写出信息窗口和 YYYY-MM-DD 日期")
    summary = section(text, "## 执行摘要")
    if summary is not None:
        count = sum(1 for line in summary.splitlines() if BULLET.match(line))
        if count < 5 or count > 8:
            found.append(f"执行摘要有 {count} 条，需要 5 到 8 条")
    gap = section(text, "## 信息缺口与检索说明")
    if gap is not None and "剔除" not in gap:
        found.append("信息缺口与检索说明需要写明剔除情况")
    return found


def daily_problems(text: str) -> list[str]:
    found: list[str] = []
    if not re.search(r"^# ESG招标日报\s+\d{4}-\d{2}-\d{2}\s*$", text, re.M):
        found.append("标题必须是：# ESG招标日报 YYYY-MM-DD")
    if "检索窗口" not in text:
        found.append("需要写出检索窗口")
    for word in BANNED:
        if word.lower() in text.lower():
            found.append(f"出现禁止字样：{word}")
    if "今日无新增ESG相关招标。" in text:
        return found
    chunks = re.split(r"^## ", text, flags=re.M)[1:]
    if not chunks:
        found.append("有新增时，每条公告要用二级标题")
        return found
    for index, chunk in enumerate(chunks, start=1):
        if "采购人" not in chunk:
            found.append(f"第{index}条缺少采购人")
        if "相关原因" not in chunk:
            found.append(f"第{index}条缺少相关原因")
        if "http" not in chunk:
            found.append(f"第{index}条缺少链接")
    return found


def self_test() -> int:
    links = "\n".join(f"- 事实｜[来源](https://example.com/{i})" for i in range(8))
    summary = "\n".join(f"- 见脚本统计：要点{i}｜[来源](https://example.com/s{i})" for i in range(1, 6))
    good = f"""
# ESG与双碳中标信息汇总（2024-01-01 至 2025-12-31）

## 报告信息

- 信息窗口：2024-01-01 至 2025-12-31

本报告是公开网络样本，不是全国招标全量统计。

## 执行摘要

{summary}

## 一、口径与样本

说明。

## 二、热点招标主题

说明。{links}

## 三、中标金额分布

### 脚本统计

- 中标金额披露率：50.0%（1/2）

### 怎么读这些数字

披露率有限。

## 四、结构观察

说明。

## 五、对业务的含义

说明。

## 信息缺口与检索说明

- 候选 10，入选 4，剔除 6。

## 信源与明细附录

见上。
"""
    if digest_problems(good):
        print("digest self-test failed")
        for item in digest_problems(good):
            print(f"- {item}")
        return 1
    daily = """
# ESG招标日报 2099-01-02

检索窗口：2099-01-01 至 2099-01-02（Asia/Shanghai）
今日新增 1 条。

## 1. 示例公告

- 采购人：某局
- 相关原因：原文「ESG报告」
- 链接：https://example.com/bid
"""
    if daily_problems(daily):
        print("daily self-test failed", daily_problems(daily))
        return 1
    quiet = """
# ESG招标日报 2099-01-02

检索窗口：2099-01-01 至 2099-01-02（Asia/Shanghai）
今日无新增ESG相关招标。
"""
    if daily_problems(quiet):
        print("quiet daily failed", daily_problems(quiet))
        return 1
    print("OK")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="检查 ESG 投标报告")
    parser.add_argument("report", nargs="?")
    parser.add_argument("--mode", choices=("digest", "daily"), default="digest")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv[1:])
    if args.self_test:
        return self_test()
    if not args.report:
        print("用法：python check_report.py [--mode digest|daily] <报告.md>", file=sys.stderr)
        return 2
    path = Path(args.report)
    if not path.is_file():
        print(f"找不到报告：{path}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8-sig")
    found = daily_problems(text) if args.mode == "daily" else digest_problems(text)
    if found:
        print(f"未通过，{len(found)} 项：")
        for item in found:
            print(f"- {item}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
