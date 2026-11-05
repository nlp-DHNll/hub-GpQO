"""FastAPI 应用：查询接口、SSE 阶段流、网页前端托管。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from ..config import PROJECT_ROOT, settings
from ..db.catalog import get_catalog
from ..graph.runner import get_agent_graph
from .schemas import QueryRequest, QueryResponse

logger = logging.getLogger(__name__)

WEB_DIR = PROJECT_ROOT / "web"

app = FastAPI(
    title="Chinook SQL Agent",
    description="LangGraph 编排的 SQL Agent：自然语言 -> SQL -> 只读执行 -> 中文答案",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="前端页面缺失")
    return FileResponse(index_file, media_type="text/html; charset=utf-8")


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "db": settings.db_path.name,
        "primary_model": settings.primary_model,
        "summary_model": settings.summary_model,
    }


@app.get("/api/schema")
async def schema_overview() -> dict:
    """侧边栏用的库结构概览：表名、行数、字段。"""

    catalog = get_catalog()
    tables = [
        {
            "name": name,
            "rows": catalog._tables[name].row_count,
            "columns": [column.name for column in catalog._tables[name].columns],
        }
        for name in catalog.table_names
    ]
    return {"database": catalog.db_path.name, "tables": tables}


@app.post("/api/query", response_model=QueryResponse)
async def query(payload: QueryRequest) -> QueryResponse:
    started = time.perf_counter()
    try:
        result = await get_agent_graph().run_full(payload.question)
    except Exception as exc:  # noqa: BLE001 - 对外返回可读错误
        logger.exception("api query failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return QueryResponse(
        output=result["output"],
        columns=result["columns"],
        rows=result["rows"],
        stages=result["stages"],
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
    )


@app.post("/api/query/stream")
async def query_stream(payload: QueryRequest) -> StreamingResponse:
    """SSE 流：stage_start / stage_end / final / error。"""

    async def event_source() -> AsyncIterator[str]:
        started = time.perf_counter()
        try:
            async for event in get_agent_graph().stream(payload.question):
                if event.get("type") == "final":
                    event["elapsed_ms"] = round(
                        (time.perf_counter() - started) * 1000, 1
                    )
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001 - 前端展示错误而不是断流
            logger.exception("api stream failed")
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
