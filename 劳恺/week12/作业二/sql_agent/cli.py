"""命令行入口：python -m sql_agent "查询问题"。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from .config import settings
from .logging_config import configure_logging
from .workflow import SQLAgentWorkflow


def _emit_json(payload: str) -> None:
    """JSON 按 UTF-8 输出。

    Windows 控制台默认 GBK，结果里出现非 GBK 字符（如客户名 Helena Holý 的 ý）
    时 `print` 会抛 UnicodeEncodeError，让整个 CLI 崩掉。
    """

    try:
        print(payload)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(payload.encode("utf-8") + b"\n")


def _read_question(args: list[str]) -> str:
    if args:
        return " ".join(args)
    if sys.stdin.isatty():
        print("请输入查询问题：", file=sys.stderr, end="", flush=True)
        return input()
    return sys.stdin.read().rstrip("\r\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chinook 数据库 SQL Agent")
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

    if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")):
        print(
            "缺少 API key。请先设置 DEEPSEEK_API_KEY（推荐）或 OPENAI_API_KEY，例如：\n"
            "  export DEEPSEEK_API_KEY=sk-...\n"
            f"  export OPENAI_BASE_URL={settings.base_url}  # 可选",
            file=sys.stderr,
        )
        raise SystemExit(1)

    question = _read_question(args.text)
    output = asyncio.run(SQLAgentWorkflow().run(question))
    _emit_json(json.dumps(output.model_dump(), ensure_ascii=False, indent=2))
    if output.error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
