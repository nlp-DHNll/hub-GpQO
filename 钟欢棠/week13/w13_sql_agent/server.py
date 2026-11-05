"""作业 2 后端：FastAPI 服务，把网页对话请求转发给 LangGraph SQL Agent。

运行：
    uvicorn server:app --reload --port 8000
    # 或
    python server.py

前端页面： http://127.0.0.1:8000/
对话接口： POST /api/chat  body={"message": "自然语言问题"}
"""

from __future__ import annotations

import os
from pathlib import Path

# 必须在导入 sql_agent.config（它会立刻读环境变量生成 settings）之前加载 .env，
# 否则 settings 会一直使用代码里的默认值，.env 中的 base_url / model 不生效。
try:  # python-dotenv 可选：有 .env 时自动加载 OPENAI_API_KEY 等
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sql_agent.config import settings
from sql_agent.graph import get_agent
from sql_agent.logging_config import configure_logging

configure_logging(os.getenv("SQL_AGENT_LOG_LEVEL", "INFO"))

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

app = FastAPI(title="SQL Agent 对话查询", version="1.0")


# 允许前端单独部署时跨域访问；同源部署下无影响。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str  # "user" / "assistant"
    content: str
    sql: str | None = None
    steps: list[str] | None = None


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    answer: str
    sql: str | None = None
    tables: list[str] = []
    row_count: int = 0
    evidence: list[str] = []
    caveats: list[str] = []
    steps: list[str] = []
    error: str | None = None


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "db": str(settings.db_path), "model": settings.primary_model}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    question = (req.message or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="message 不能为空")

    agent = get_agent()
    output = await agent.arun(question)
    return ChatResponse(
        answer=output.answer,
        sql=output.sql,
        tables=output.tables,
        row_count=output.row_count,
        evidence=output.evidence,
        caveats=output.caveats,
        steps=output.steps,
        error=output.error,
    )


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


# 把前端静态资源（css/js/图片）挂载到 /static
app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="static",
)


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=bool(os.getenv("DEV", "")),
    )
