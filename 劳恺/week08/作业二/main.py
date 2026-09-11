"""深度研究助手 · uvicorn 启动入口。

启动：
    python main.py
或者：
    uvicorn main:app --host 0.0.0.0 --port 8000

环境变量从 .env 加载。FastAPI 自动文档：/docs
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

# 注意：load_dotenv 必须在其他模块导入之前，因为它们在 import 时会读 env
from dotenv import load_dotenv

load_dotenv()

import uvicorn
from fastapi import FastAPI

from app.api.routes import router
from app.search.bocha import close_bocha


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期：启动 / 关闭。

    启动：task_store 会在首次访问时自动从 data/tasks/ 恢复，无需此处操作。
    关闭：关闭 Bocha 的 httpx.AsyncClient。
    """
    yield
    await close_bocha()


app = FastAPI(
    title="深度研究助手",
    description="输入研究主题，自动检索 → 阅读 → 迭代 → 综合生成带来源引用的报告",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=False)
