"""FastAPI 入口:研究 API + 托管 frontend/dist(build 后的演示模式)。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import WEEK08_DIR
from app.graph.builder import open_checkpointer

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with open_checkpointer() as cp:
        app.state.checkpointer = cp
        yield


app = FastAPI(title="深度研究助手", lifespan=lifespan)
app.include_router(router, prefix="/api")

# 演示模式:托管前端构建产物(存在时);开发模式走 vite dev proxy
_dist = WEEK08_DIR / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
