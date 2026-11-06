"""FastAPI 前后端接口：网页提交问题，由 LangGraph 工作流处理。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .graph_workflow import SQLAgentWorkflow
from .models import WorkflowOutput

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(
    title="Chinook SQL Agent",
    description="通过自然语言问题查询 Chinook 示例数据库",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


class QueryRequest(BaseModel):
    """网页查询请求。"""

    question: str = Field(min_length=1, max_length=1000)


@lru_cache(maxsize=1)
def get_workflow() -> SQLAgentWorkflow:
    """进程内复用工作流和数据库目录。"""

    return SQLAgentWorkflow()


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "model": settings.primary_model}


@app.post("/api/query", response_model=WorkflowOutput)
async def query(request: QueryRequest) -> WorkflowOutput:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="请输入查询问题。")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="服务未配置 OPENAI_API_KEY，请检查项目根目录的 .env 文件。",
        )
    return await get_workflow().run(question)


def main() -> None:
    """启动本地 Web 服务。"""

    uvicorn.run(
        "sql_agent_web.web:app",
        host=os.getenv("SQL_AGENT_HOST", "127.0.0.1"),
        port=int(os.getenv("SQL_AGENT_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
