"""命令行入口：python -m sql_agent "查询问题"。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from .config import settings
from .graph import SQLAgentGraph
from .logging_config import configure_logging


def _read_question(args: list[str]) -> str:
    if args:
        return " ".join(args)
    if sys.stdin.isatty():
        print("请输入查询问题：", file=sys.stderr, end="", flush=True)
        return input()
    return sys.stdin.read().rstrip("\r\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chinook 数据库 SQL Agent（LangChain 版）")
    parser.add_argument("text", nargs="*", help="自然语言查询问题")
    parser.add_argument(
        "--log-level",
        default=os.getenv("SQL_AGENT_LOG_LEVEL", "INFO"),
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别，默认读取 SQL_AGENT_LOG_LEVEL 或 INFO",
    )
    args = parser.parse_args()
    configure_logging(args.log_level)

    if not settings.api_key:
        print(
            "缺少 API key。请设置环境变量或在项目根 .env 中配置：\n"
            "  API_KEY=sk-...\n"
            "  BASE_URL=https://...  # 可选\n"
            "  BASE_MODEL=qwen3.8-max  # 可选\n"
            "（也兼容 OPENAI_API_KEY / OPENAI_BASE_URL）",
            file=sys.stderr,
        )
        raise SystemExit(1)

    question = _read_question(args.text)
    output = asyncio.run(SQLAgentGraph().run(question))
    print(json.dumps(output.model_dump(), ensure_ascii=False, indent=2))
    if output.error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
