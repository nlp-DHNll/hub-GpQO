"""FastAPI 应用工厂：静态页面 + REST 问答 + SSE 流式执行轨迹。

设计要点：

1. **应用工厂** ``create_app(service=...)``：测试可以注入脚本化服务，
   不碰真实模型，也不依赖环境变量；
2. **REST 与 SSE 并存**：``POST /api/chat`` 返回一次性 JSON，
   ``POST /api/chat/stream`` 逐条推送阶段事件，前端能看到 Agent 正在做什么；
3. **错误也要是稳定 JSON**：模型没配 Key、网络失败、SQL 修复失败，
   都由 ``ChatService`` 转成 ``ChatResponse``，前端永远有内容可渲染。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# 先导入 .config：它会加载 .env 并执行 paths.py，把作业一加入 sys.path。
from .config import web_settings
from .paths import AGENT_ROOT, PROJECT_ROOT, STATIC_DIR
from .schemas import ChatRequest, ChatResponse
from .service import ChatService

from sql_agent_lg.config import settings as agent_settings

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- 工具


def _sse(payload: dict[str, Any]) -> str:
    """把一条事件编码成 SSE 帧。"""

    body = json.dumps(
        jsonable_encoder(payload),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"data: {body}\n\n"


def _error_response(message: str, error: str) -> ChatResponse:
    return ChatResponse(
        ok=False,
        question=message,
        answer=f"处理失败：{error}",
        error=error,
        events=[
            {
                "node": "error",
                "label": "处理失败",
                "status": "error",
                "detail": " ".join(str(error).split())[:600],
                "elapsed_ms": 0,
            }
        ],
    )


def _build_default_service() -> ChatService:
    """按环境变量选择真实服务或离线演示服务。"""

    if web_settings.demo_mode:
        from .demo import create_demo_service

        logger.info("stage=app_start mode=demo db=%s", agent_settings.db_path)
        return create_demo_service()

    logger.info(
        "stage=app_start mode=live model=%s db=%s has_api_key=%s",
        agent_settings.primary_model,
        agent_settings.db_path,
        agent_settings.has_api_key,
    )
    return ChatService()


# --------------------------------------------------------------------- 应用


def create_app(service: ChatService | None = None) -> FastAPI:
    """创建 FastAPI 应用。

    ``service`` 为空时按 ``SQL_AGENT_WEB_DEMO`` 自动选择：
    演示模式用内置安全 SQL，正常模式用作业一的 LangGraph。
    """

    app = FastAPI(
        title=web_settings.title,
        version=web_settings.version,
        description="基于 LangGraph SQL Agent 的 Chinook 数据库问答服务",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    chat_service = service or _build_default_service()
    app.state.chat_service = chat_service

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    else:  # pragma: no cover - 只有目录被误删才会触发
        logger.warning("静态目录不存在：%s", STATIC_DIR)

    # ------------------------------------------------------------- 页面

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        index_file = STATIC_DIR / "index.html"
        if not index_file.exists():  # pragma: no cover
            raise HTTPException(500, "static/index.html 不存在")
        return FileResponse(index_file, media_type="text/html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        icon = STATIC_DIR / "favicon.svg"
        if not icon.exists():  # pragma: no cover
            raise HTTPException(404, "favicon 不存在")
        return FileResponse(icon, media_type="image/svg+xml")

    # ------------------------------------------------------------- 元信息

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """前端启动时读取：模式、模型、数据库与图配置。"""

        db_path = Path(agent_settings.db_path)
        return {
            "ok": True,
            "title": web_settings.title,
            "version": web_settings.version,
            "demo_mode": web_settings.demo_mode,
            "llm_configured": agent_settings.has_api_key,
            "model": agent_settings.primary_model,
            "summary_model": agent_settings.summary_model,
            "base_url": agent_settings.base_url,
            "db": {
                "path": str(db_path),
                "name": db_path.name,
                "exists": db_path.exists(),
            },
            "contextualize": web_settings.contextualize,
            "max_repair_attempts": agent_settings.max_repair_attempts,
            "max_ui_rows": web_settings.max_ui_rows,
            "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        """给 README / 调试用的路径信息（不包含任何密钥）。"""

        return {
            "project_root": str(PROJECT_ROOT),
            "agent_root": str(AGENT_ROOT),
            "static_dir": str(STATIC_DIR),
            "db_path": str(agent_settings.db_path),
            "demo_mode": web_settings.demo_mode,
        }

    # ------------------------------------------------------------- 一次性问答

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest) -> ChatResponse:
        if not payload.message.strip():
            raise HTTPException(400, "问题不能为空")
        try:
            return await chat_service.run(payload.message, payload.history)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ------------------------------------------------------------- 流式问答

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatRequest) -> StreamingResponse:
        if not payload.message.strip():
            raise HTTPException(400, "问题不能为空")

        async def event_stream():
            # 先发一条 start，让前端立刻知道连接成功，而不是干等模型。
            yield _sse(
                {
                    "type": "start",
                    "demo_mode": web_settings.demo_mode,
                    "title": web_settings.title,
                }
            )
            try:
                async for item in chat_service.stream(
                    payload.message, payload.history
                ):
                    if item.get("type") == "final" and "response" in item:
                        item["response"] = item["response"].model_dump()
                    yield _sse(item)
            except asyncio.CancelledError:  # 浏览器断开连接，不算错误
                raise
            except ValueError as exc:
                yield _sse(
                    {
                        "type": "final",
                        "response": _error_response(
                            payload.message, str(exc)
                        ).model_dump(),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - 流一旦开始只能发事件
                logger.exception("chat stream failed")
                yield _sse(
                    {
                        "type": "final",
                        "response": _error_response(
                            payload.message, str(exc)
                        ).model_dump(),
                    }
                )
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # 关闭 Nginx 缓冲，保证逐条到达
            },
        )

    return app


__all__ = ["create_app"]
