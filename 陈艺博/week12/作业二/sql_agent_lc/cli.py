"""命令行入口：python run.py "总共有多少张专辑？"

stdout 只有最终 JSON，日志走 stderr，方便管道处理（与原版一致）。

常用参数：
    --log-level DEBUG|INFO|WARNING|ERROR   日志级别
    --show-catalog                         只打印数据库目录，不调用模型（不需要 API Key）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from .config import settings
from .logging_config import configure_logging


def _read_question(args: list[str]) -> str:
    if args:
        return " ".join(args)
    if sys.stdin.isatty():
        print("请输入查询问题：", file=sys.stderr, end="", flush=True)
        return input()
    return sys.stdin.read().rstrip("\r\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chinook 数据库 SQL Agent（LangChain 版）")
    parser.add_argument("text", nargs="*", help="自然语言查询问题")
    parser.add_argument(
        "--log-level",
        default=os.getenv("SQL_AGENT_LOG_LEVEL", "INFO"),
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别，默认读 SQL_AGENT_LOG_LEVEL 或 INFO",
    )
    parser.add_argument(
        "--show-catalog",
        action="store_true",
        help="只打印数据库目录（表、字段、外键），不调用模型",
    )
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    from .db.catalog import get_catalog

    if args.show_catalog:
        print(get_catalog().render_catalog())
        return 0

    if not settings.has_api_key:
        envs = " / ".join(settings.api_key_envs)
        print(
            "缺少 API Key。请在项目根目录新建 .env（可参考 .env.example）并填写：\n"
            f"  {envs}=sk-...\n"
            f"  SQL_AGENT_BASE_URL={settings.base_url}\n"
            "或先运行离线演示：python demo_offline.py",
            file=sys.stderr,
        )
        return 1

    from .workflow import SQLAgentWorkflow

    question = _read_question(args.text)
    output = asyncio.run(SQLAgentWorkflow().run(question))
    print(json.dumps(output.model_dump(), ensure_ascii=False, indent=2))
    return 1 if output.error else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
