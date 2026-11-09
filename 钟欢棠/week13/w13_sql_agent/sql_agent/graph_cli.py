"""作业 1 演示：用 LangGraph 复现的 SQL Agent 命令行入口。

用法：
    python -m sql_agent.graph_cli "查询问题"
    python -m sql_agent.graph_cli            # 使用内置示例问题
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from .config import settings
from .graph import LangGraphSQLAgent
from .logging_config import configure_logging

EXAMPLES = [
    "总共有多少位不同的艺术家？",
    "人气最高的 5 张专辑分别是哪些？",
    "每个员工的下属数量是多少？",
]


def _read_question(args: list[str]) -> str:
    if args:
        return " ".join(args)
    return EXAMPLES[0]


async def _run(question: str) -> None:
    agent = LangGraphSQLAgent()
    output = await agent.arun(question)
    print(json.dumps(output.model_dump(), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="LangGraph SQL Agent（Chinook）")
    parser.add_argument("text", nargs="*", help="自然语言查询问题")
    parser.add_argument(
        "--log-level",
        default=os.getenv("SQL_AGENT_LOG_LEVEL", "WARNING"),
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()
    configure_logging(args.log_level)

    if not os.getenv("OPENAI_API_KEY"):
        print(
            "缺少 OPENAI_API_KEY。请先设置环境变量，例如：\n"
            "  set OPENAI_API_KEY=sk-...\n"
            f"  set OPENAI_BASE_URL={settings.base_url}  # 可选",
            file=sys.stderr,
        )
        raise SystemExit(1)

    question = _read_question(args.text)
    asyncio.run(_run(question))


if __name__ == "__main__":
    main()
