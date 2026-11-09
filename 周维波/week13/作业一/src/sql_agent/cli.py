"""命令行入口：查询问题，或启动网页服务。

    PYTHONPATH=src python -m sql_agent "总共有多少张专辑？"
    PYTHONPATH=src python -m sql_agent --serve --port 8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from .config import settings
from .graph.runner import get_agent_graph
from .logging_config import configure_logging


def _read_question(args: list[str]) -> str:
    if args:
        return " ".join(args)
    if sys.stdin.isatty():
        print("请输入查询问题：", file=sys.stderr, end="", flush=True)
        return input()
    return sys.stdin.read().rstrip("\r\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chinook 数据库 SQL Agent（LangGraph 版）")
    parser.add_argument("text", nargs="*", help="自然语言查询问题")
    parser.add_argument("--serve", action="store_true", help="启动网页对话服务")
    parser.add_argument("--host", default="127.0.0.1", help="服务监听地址")
    parser.add_argument("--port", type=int, default=8000, help="服务端口")
    parser.add_argument(
        "--log-level",
        default=os.getenv("SQL_AGENT_LOG_LEVEL", "INFO"),
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别，默认读取 SQL_AGENT_LOG_LEVEL 或 INFO",
    )
    args = parser.parse_args()
    configure_logging(args.log_level)

    if args.serve:
        import uvicorn

        print(f"网页服务已启动：http://{args.host}:{args.port}", file=sys.stderr)
        uvicorn.run(
            "sql_agent.api.app:app",
            host=args.host,
            port=args.port,
            log_level=args.log_level.lower(),
        )
        return

    if not os.getenv("OPENAI_API_KEY"):
        print(
            "缺少 OPENAI_API_KEY。请先设置环境变量，例如：\n"
            "  set OPENAI_API_KEY=sk-...\n"
            f"  set OPENAI_BASE_URL={settings.base_url}  # 可选",
            file=sys.stderr,
        )
        raise SystemExit(1)

    question = _read_question(args.text)
    output = asyncio.run(get_agent_graph().run(question))
    print(json.dumps(output.model_dump(), ensure_ascii=False, indent=2))
    if output.error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
