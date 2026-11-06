"""FastAPI 服务：把 SQLAgentWorkflow 暴露成 Web API，并托管静态前端。"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import settings
from ..logging_config import configure_logging
from ..models import WorkflowOutput
from ..workflow import SQLAgentWorkflow

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class QueryRequest(BaseModel):
    """一次查询请求。"""

    question: str = Field(
        min_length=1,
        max_length=2000,
        description="自然语言问题，例如“总共有多少张专辑？”",
    )


class QueryResponse(WorkflowOutput):
    """在 CLI 输出之外补充服务端耗时，便于前端展示。"""

    elapsed_ms: int = 0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动时构建一次工作流（catalog 有进程级缓存），请求之间复用。"""

    configure_logging(os.getenv("SQL_AGENT_LOG_LEVEL", "INFO"))
    app.state.workflow = SQLAgentWorkflow()
    catalog = app.state.workflow.agent_graph.catalog
    logger.info(
        "webapp ready db=%s tables=%d model=%s",
        catalog.db_path,
        len(catalog.table_names),
        settings.primary_model,
    )
    yield


app = FastAPI(
    title="Chinook SQL Agent",
    description="自然语言查询 Chinook 数据库的 LangGraph SQL Agent",
    version="0.2.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """返回单页前端。"""

    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    """前端用它显示连接状态和模型信息。"""

    workflow: SQLAgentWorkflow = app.state.workflow
    catalog = workflow.agent_graph.catalog
    return {
        "status": "ok",
        "db": str(catalog.db_path),
        "tables": len(catalog.table_names),
        "model": settings.primary_model,
        "summary_model": settings.summary_model,
        "has_api_key": bool(os.getenv("OPENAI_API_KEY")),
    }


@app.post("/api/query", response_model=QueryResponse)
async def query(payload: QueryRequest) -> QueryResponse:
    """执行一次自然语言查询，返回答案、SQL 和结果行。"""

    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空。")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="服务端未配置 OPENAI_API_KEY，请设置环境变量后重启服务。",
        )

    started = time.perf_counter()
    output = await app.state.workflow.run(question)
    data = output.model_dump()
    data["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return QueryResponse(**data)


def main() -> None:
    """命令行入口：sql-agent-web 或 python -m sql_agent.webapp.server。"""

    import uvicorn

    parser = argparse.ArgumentParser(description="Chinook SQL Agent Web 服务")
    parser.add_argument("--host", default=settings.web_host, help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=settings.web_port, help="监听端口，默认 8000")
    parser.add_argument(
        "--log-level",
        default=os.getenv("SQL_AGENT_LOG_LEVEL", "INFO"),
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    args = parser.parse_args()

    configure_logging(args.log_level)
    uvicorn.run(
        "sql_agent.webapp.server:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
