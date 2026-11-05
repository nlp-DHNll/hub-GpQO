"""Checkpointer 工厂：AsyncSqliteSaver 落盘（课件 03_持久化 + 04_回放 的基础）。

图的入口（run / astream / replay）全部是异步路径，而同步 SqliteSaver 在
langgraph-checkpoint-sqlite 3.x 里不支持 async 方法（aget_tuple 直接
NotImplementedError），因此 CLI、回放与作业2 服务端统一用 AsyncSqliteSaver。

用法（异步上下文管理器，退出时自动落盘收尾）：

    async with open_checkpointer() as checkpointer:
        graph = SQLAgentGraph(checkpointer=checkpointer)
        ...
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .config import settings


@asynccontextmanager
async def open_checkpointer(path: Path | None = None) -> AsyncGenerator[AsyncSqliteSaver]:
    """打开（必要时创建）checkpoint 数据库，yield 一个 AsyncSqliteSaver。"""

    db_path = Path(path or settings.checkpoint_db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        yield saver
