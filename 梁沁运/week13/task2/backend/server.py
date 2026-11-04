"""FastAPI 服务器 — 将 SQL Agent 暴露为 REST API，支持 SSE 流式推送工作流更新。"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# 将 task1 的 src 加入 sys.path
TASK1_SRC = Path(__file__).resolve().parent.parent.parent / "task1" / "src"
sys.path.insert(0, str(TASK1_SRC))

from sql_agent.agents import Agents
from sql_agent.config import get_deepseek_settings, get_obs_settings
from sql_agent.db.catalog import SchemaCatalog
from sql_agent.graph import build_graph
from sql_agent.models import FinalAnswer
from sql_agent.observability import TokenUsageLogger

app = FastAPI(title="SQL Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str = Field(..., description="自然语言查询问题", min_length=1)
    db_path: str = Field(default="", description="SQLite 数据库路径")


class WorkflowEvent(BaseModel):
    type: str  # "stage", "answer", "error", "complete"
    stage: str | None = None
    data: dict | None = None
    timestamp: float = Field(default_factory=time.time)


# 全局 catalog（启动时加载）
_catalog: SchemaCatalog | None = None


def get_catalog() -> SchemaCatalog:
    global _catalog
    if _catalog is None:
        db_path = Path(__file__).resolve().parent.parent.parent / "task1" / "ref" / "chinook.db"
        _catalog = SchemaCatalog(str(db_path))
        _catalog.load()
    return _catalog


@app.get("/api/health")
async def health_check():
    """健康检查 + API key 状态。"""
    settings = get_deepseek_settings()
    catalog = get_catalog()
    return {
        "status": "ok",
        "api_key_configured": settings.is_configured,
        "tables": len(catalog.tables),
    }


@app.post("/api/query")
async def query_sync(req: QueryRequest):
    """同步查询接口：等待完整结果后返回。"""
    settings = get_deepseek_settings()
    if not settings.is_configured:
        raise HTTPException(status_code=503, detail="未配置 DEEPSEEK_API_KEY 环境变量")

    catalog = get_catalog()
    agents = Agents()
    obs = get_obs_settings()

    # 运行完整工作流
    graph = build_graph(catalog, agents).compile()
    config: dict = {}
    if obs.enable_callback_logger:
        config["callbacks"] = [TokenUsageLogger()]

    final_answer: FinalAnswer | None = None
    stages: list[dict] = []

    async for chunk in graph.astream(
        {"question": req.question},
        stream_mode="updates",
        config=config,
    ):
        for node_name, update in chunk.items():
            stage_info = {
                "node": node_name,
                "stage": update.get("stage", node_name),
                "data": {},
            }
            # 提取关键信息
            if update.get("selection"):
                sel = update["selection"]
                stage_info["data"]["selection"] = {
                    "tables": sel.tables,
                    "reason": sel.reason,
                    "confidence": sel.confidence,
                    "needs_clarification": sel.needs_clarification,
                    "clarification_question": sel.clarification_question,
                }
            if update.get("validation"):
                v = update["validation"]
                stage_info["data"]["validation"] = {
                    "ok": v.ok,
                    "code": v.code.value if v.code else None,
                    "message": v.message,
                }
            if update.get("sql"):
                stage_info["data"]["sql"] = update["sql"]
            if update.get("execution"):
                e = update["execution"]
                stage_info["data"]["execution"] = {
                    "columns": e.columns,
                    "row_count": e.row_count,
                    "truncated": e.truncated,
                    "rows": e.rows[:20],  # 只返回前20行
                }
            if update.get("last_error"):
                stage_info["data"]["error"] = update["last_error"]
            if update.get("repair_attempts") is not None:
                stage_info["data"]["repair_attempts"] = update["repair_attempts"]
            if update.get("answer"):
                final_answer = update["answer"]

            stages.append(stage_info)

    if final_answer is None:
        final_answer = FinalAnswer(answer="工作流未产生最终答案。")

    return {
        "answer": final_answer.model_dump(),
        "stages": stages,
    }


@app.post("/api/query/stream")
async def query_stream(req: QueryRequest) -> StreamingResponse:
    """流式查询接口：通过 SSE 实时推送每个工作流更新。"""
    settings = get_deepseek_settings()
    if not settings.is_configured:
        raise HTTPException(status_code=503, detail="未配置 DEEPSEEK_API_KEY 环境变量")

    async def event_generator() -> AsyncGenerator[str, None]:
        catalog = get_catalog()
        agents = Agents()
        obs = get_obs_settings()

        graph = build_graph(catalog, agents).compile()
        config: dict = {}
        if obs.enable_callback_logger:
            config["callbacks"] = [TokenUsageLogger()]

        # 发送初始事件
        yield f"data: {json.dumps(WorkflowEvent(type='stage', stage='start', data={'question': req.question}).model_dump(), ensure_ascii=False)}\n\n"

        try:
            async for chunk in graph.astream(
                {"question": req.question},
                stream_mode="updates",
                config=config,
            ):
                for node_name, update in chunk.items():
                    event_data = {
                        "node": node_name,
                        "stage": update.get("stage", node_name),
                    }

                    if update.get("selection"):
                        sel = update["selection"]
                        event_data["selection"] = {
                            "tables": sel.tables,
                            "reason": sel.reason,
                            "confidence": sel.confidence,
                            "needs_clarification": sel.needs_clarification,
                            "clarification_question": sel.clarification_question,
                        }
                    if update.get("validation"):
                        v = update["validation"]
                        event_data["validation"] = {
                            "ok": v.ok,
                            "code": v.code.value if v.code else None,
                            "message": v.message,
                        }
                    if update.get("sql"):
                        event_data["sql"] = update["sql"]
                    if update.get("execution"):
                        e = update["execution"]
                        event_data["execution"] = {
                            "columns": e.columns,
                            "row_count": e.row_count,
                            "truncated": e.truncated,
                            "rows": e.rows[:20],
                        }
                    if update.get("last_error"):
                        event_data["error"] = update["last_error"]
                    if update.get("repair_attempts") is not None:
                        event_data["repair_attempts"] = update["repair_attempts"]
                    if update.get("answer"):
                        event_data["answer"] = update["answer"].model_dump()
                    if update.get("selection_retry_count") is not None:
                        event_data["selection_retry_count"] = update["selection_retry_count"]

                    yield f"data: {json.dumps(WorkflowEvent(type='stage', stage=update.get('stage', node_name), data=event_data).model_dump(), ensure_ascii=False)}\n\n"

            # 完成
            yield f"data: {json.dumps(WorkflowEvent(type='complete', stage='done', data={}).model_dump(), ensure_ascii=False)}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps(WorkflowEvent(type='error', stage='error', data={'error': str(exc)}).model_dump(), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
