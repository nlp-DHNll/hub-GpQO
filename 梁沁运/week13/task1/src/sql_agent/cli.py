"""cli.py — v1 对外入口。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .agents import Agents
from .config import get_deepseek_settings, get_obs_settings
from .db.catalog import SchemaCatalog
from .observability import run_workflow


def main():
    parser = argparse.ArgumentParser(
        description="SQL Agent — 自然语言查询 Chinook 数据库"
    )
    parser.add_argument(
        "--question", "-q",
        required=True,
        help="自然语言查询问题",
    )
    parser.add_argument(
        "--db",
        default="ref/chinook.db",
        help="SQLite 数据库路径（默认: ref/chinook.db）",
    )
    args = parser.parse_args()

    # 检查 API key
    settings = get_deepseek_settings()
    if not settings.is_configured:
        print(
            "错误：未设置 DEEPSEEK_API_KEY 环境变量。\n"
            "请设置后重试：export DEEPSEEK_API_KEY=your_key",
            file=sys.stderr,
        )
        sys.exit(1)

    # 加载 catalog
    catalog = SchemaCatalog(args.db)
    catalog.load()

    # 构建 agents
    agents = Agents()

    # 可观测性配置
    obs = get_obs_settings()

    # 运行工作流
    answer = asyncio.run(
        run_workflow(
            question=args.question,
            catalog=catalog,
            agents=agents,
            obs=obs,
        )
    )

    # 输出 FinalAnswer JSON 到 stdout
    print(answer.model_dump_json(indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
