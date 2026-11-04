"""命令行入口：单问模式（week12 兼容）+ 多轮 REPL（week13 新增）。

单问：python -m sql_agent "总共有多少张专辑？" [--thread ID]
  输出最终 JSON（stdout），进度日志在 stderr；--thread 指定会话续跑。

REPL：python -m sql_agent [--thread ID]
  多轮对话：同 thread 的历史自动注入（澄清回答后可继续追问）。
  命令：/help /reset /resume <thread_id> /thread /exit
  进度行实时打印主图节点流转（stream_mode="updates"）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from .checkpoint import open_checkpointer
from .config import settings
from .graph import SQLAgentGraph
from .logging_config import configure_logging
from .models import WorkflowOutput

PROMPT = "sql-agent> "

HELP_TEXT = """命令：
  /reset            开启新会话（新 thread_id）
  /resume <id>      恢复指定会话（需 checkpoint 数据库中存在该 thread）
  /thread           显示当前 thread_id
  /help             显示本帮助
  /exit             退出
其他输入按查询问题处理；Ctrl+D 退出。"""


def _print_final(output: WorkflowOutput, thread_id: str) -> None:
    print("─" * 56)
    print(f"答：{output.answer}")
    if output.sql:
        print(f"SQL：{output.sql}")
    meta = [
        f"表：{'、'.join(output.tables) if output.tables else '-'}",
        f"行数：{output.row_count}",
    ]
    if output.repair_attempts:
        meta.append(f"修复：{output.repair_attempts} 次")
    print("  ｜ ".join(meta))
    for caveat in output.caveats:
        print(f"⚠ {caveat}")
    if output.error:
        print(f"✗ 错误：{output.error}")
    print(f"（thread: {thread_id}，/resume 可在新进程继续本会话）")


async def _run_turn_streamed(
    graph: SQLAgentGraph, question: str, thread_id: str | None
) -> str:
    """跑一轮并实时打印节点进度，返回实际使用的 thread_id。"""

    turn_input, config = await graph.prepare_turn(question, thread_id)
    thread_id = str(config["configurable"]["thread_id"])
    final: WorkflowOutput | None = None

    async for chunk in graph.app.astream(
        turn_input, config=config, stream_mode="updates"
    ):
        if not isinstance(chunk, dict):
            continue
        for node, update in chunk.items():
            stage = update.get("stage") if isinstance(update, dict) else None
            marker = "❓" if stage == "clarify" else "▸"
            print(f"  {marker} {node} → {stage}")
            if isinstance(update, dict) and update.get("final") is not None:
                final = update["final"]

    if final is None:
        snapshot = await graph.app.aget_state(config)
        final = snapshot.values.get("final")
    if final is None:
        final = WorkflowOutput(
            question=question, answer="SQL 执行失败。", error="no final output"
        )

    _print_final(final, thread_id)
    return thread_id


async def _single(question: str, thread_id: str | None) -> WorkflowOutput:
    async with open_checkpointer() as checkpointer:
        graph = SQLAgentGraph(checkpointer=checkpointer)
        return await graph.run(question, thread_id=thread_id)


async def _repl(thread_id: str | None) -> None:
    print("Chinook SQL Agent（LangGraph 版·多轮会话）。输入 /help 查看命令。")
    if thread_id:
        print(f"已恢复会话 thread: {thread_id}")

    async with open_checkpointer() as checkpointer:
        graph = SQLAgentGraph(checkpointer=checkpointer)
        while True:
            try:
                line = input(PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue
            if line == "/exit":
                break
            if line == "/help":
                print(HELP_TEXT)
                continue
            if line == "/reset":
                thread_id = None
                print("已开启新会话（下一问生成新 thread_id）。")
                continue
            if line == "/thread":
                print(f"当前 thread: {thread_id or '（尚未提问，下一问自动生成）'}")
                continue
            if line.startswith("/resume"):
                parts = line.split(maxsplit=1)
                if len(parts) < 2 or not parts[1].strip():
                    print("用法：/resume <thread_id>")
                    continue
                candidate = parts[1].strip()
                try:
                    snapshot = await graph.app.aget_state(graph.make_config(candidate))
                    if snapshot.values:
                        thread_id = candidate
                        print(f"已恢复会话 thread: {thread_id}")
                    else:
                        print(f"thread {candidate} 无历史记录（或数据库为空）。")
                except Exception as exc:
                    print(f"恢复失败：{exc}")
                continue
            if line.startswith("/"):
                print(f"未知命令：{line}（/help 查看可用命令）")
                continue

            thread_id = await _run_turn_streamed(graph, line, thread_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chinook 数据库 SQL Agent（LangGraph 版：子图 + 持久化多轮）"
    )
    parser.add_argument("text", nargs="*", help="自然语言查询问题；省略则进入多轮 REPL")
    parser.add_argument("--thread", help="会话 thread_id（多轮续跑 / 恢复历史会话）")
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

    if args.text:
        # 单问模式：输出 JSON（week12 兼容），进度走 stderr 日志。
        output = asyncio.run(_single(" ".join(args.text), args.thread))
        print(json.dumps(output.model_dump(), ensure_ascii=False, indent=2))
        if output.error:
            raise SystemExit(1)
        return

    asyncio.run(_repl(args.thread))


if __name__ == "__main__":
    main()
