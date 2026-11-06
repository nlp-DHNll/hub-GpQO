"""FastAPI 应用：给 Vue 前端用的 HTTP 接口。

后端工作流本身是无状态的（一次问题 -> 一次结果），所以这里**不存会话**：
对话历史由前端维护，每次请求带上 `history` 字段，后端只把它拼进提示词。

接口一览：

- `POST /api/query`        —— 跑一轮，返回完整的 `WorkflowOutput`
- `POST /api/query/stream` —— 同样的流程，但用 SSE 逐节点推送进度
- `GET  /api/health`       —— 模型、数据库、API key 是否就绪
- `GET  /api/catalog`      —— 可查询的表清单
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import settings
from ..logging_config import configure_logging
from ..models import ConversationTurn, WorkflowOutput
from ..workflow import SQLAgentWorkflow

# 前端构建产物；存在就直接由本服务托管，实现单端口部署
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

# 最多接受多少轮历史，防止提示词无限增长
MAX_HISTORY_TURNS = 10

DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


class TurnModel(BaseModel):
    """前端回传的一轮对话。"""

    question: str
    answer: str = ""
    sql: str | None = None
    tables: list[str] = Field(default_factory=list)


class QueryRequest(BaseModel):
    """一次提问。"""

    question: str = Field(min_length=1, max_length=2000)
    history: list[TurnModel] = Field(default_factory=list)


def _to_turns(history: list[TurnModel]) -> list[ConversationTurn]:
    return [
        ConversationTurn(
            question=turn.question,
            answer=turn.answer,
            sql=turn.sql,
            tables=turn.tables,
        )
        for turn in history[-MAX_HISTORY_TURNS:]
    ]


def _has_api_key() -> bool:
    return bool(os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))


def create_app() -> FastAPI:
    """构造 FastAPI 应用。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # workflow 只建一次：SchemaCatalog 是进程级缓存，而 validator /
        # executor 各自持有一个 SQLAlchemy engine 和连接池。
        configure_logging(os.getenv("SQL_AGENT_LOG_LEVEL", "INFO"))
        app.state.workflow = SQLAgentWorkflow()
        yield
        app.state.workflow = None

    app = FastAPI(
        title="Chinook SQL Agent",
        description="自然语言查询 Chinook SQLite 库",
        version="1.0.0",
        lifespan=lifespan,
    )

    origins = [
        origin.strip()
        for origin in os.getenv("SQL_AGENT_CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_workflow() -> SQLAgentWorkflow:
        workflow = getattr(app.state, "workflow", None)
        if workflow is None:
            raise RuntimeError("workflow 尚未初始化")
        return workflow

    # ------------------------------------------------------------------
    # 接口
    # ------------------------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict:
        """给前端探活：模型、数据库、key 是否就绪。"""

        workflow = getattr(app.state, "workflow", None)
        catalog = workflow.catalog if workflow else None
        return {
            "status": "ok" if _has_api_key() else "missing_api_key",
            "has_api_key": _has_api_key(),
            "model": settings.primary_model,
            "summary_model": settings.summary_model,
            "db": str(settings.db_path),
            "db_exists": settings.db_path.exists(),
            "tables": len(catalog.table_names) if catalog else 0,
        }

    @app.get("/api/catalog")
    async def catalog() -> dict:
        """可查询的表清单 + 选表 Agent 看到的目录文本。"""

        workflow = get_workflow()
        return {
            "tables": workflow.catalog.table_names,
            "catalog": workflow.catalog.render_catalog(),
        }

    @app.post("/api/query")
    async def query(request: QueryRequest) -> WorkflowOutput:
        """跑一轮，返回完整结果。

        agent 层面的失败（`error` 字段）也用 200 返回，由前端按 `status`
        分支渲染；只有请求体不合法才是 4xx。
        """

        workflow = get_workflow()
        return await workflow.run(
            request.question,
            history=_to_turns(request.history),
        )

    @app.post("/api/query/stream")
    async def query_stream(request: QueryRequest) -> StreamingResponse:
        """跑一轮，用 SSE 逐节点推送进度。

        事件类型：`stage`（某个节点跑完）、`result`（最终结果）、
        `error`（整体异常）。
        """

        workflow = get_workflow()

        async def event_source():
            async for event in workflow.stream(
                request.question,
                history=_to_turns(request.history),
            ):
                payload = dict(event)
                output = payload.get("output")
                if isinstance(output, WorkflowOutput):
                    payload["output"] = output.model_dump()
                data = json.dumps(payload, ensure_ascii=False)
                yield f"event: {payload['type']}\ndata: {data}\n\n"

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                # 关掉 nginx 一类反向代理的缓冲，否则进度会被攒到最后一次性吐出
                "X-Accel-Buffering": "no",
            },
        )

    # ------------------------------------------------------------------
    # 前端静态资源
    # ------------------------------------------------------------------

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    else:

        @app.get("/")
        async def index() -> JSONResponse:
            return JSONResponse(
                {
                    "message": "前端还没构建。开发时跑 npm run dev，构建后 npm run build。",
                    "api": "/api/health",
                }
            )

    return app


app = create_app()
