"""FastAPI 路由。

端点：
- POST   /research           提交研究任务，返回 task_id
- GET    /research/{task_id} 轮询任务状态和结果
- GET    /researches         列出最近任务
- GET    /                   健康检查
"""
from __future__ import annotations

import asyncio
import traceback
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.core.researcher import run_research
from app.core.task_store import get_task_store
from app.models import ResearchRequest, ResearchTask


router = APIRouter()


# ============================================================
# 提交任务
# ============================================================

@router.post("/research", summary="提交研究任务")
async def submit_research(req: ResearchRequest):
    """创建任务并立即返回 task_id，研究在后台异步执行。

    使用 asyncio.create_task 而不是 BackgroundTasks：
    - 后者会 await 到任务完成才释放 handler，对 2~5 分钟的研究浪费资源
    - 前者立即返回，任务在 event loop 后台跑
    - 代价：进程被 kill 时未完成任务会丢（v1 接受此限制，README §12）
    """
    store = get_task_store()
    task = store.create_task(req)
    asyncio.create_task(_safe_run(task.task_id))
    return {
        "task_id": task.task_id,
        "topic": task.topic,
        "status": task.status.value,
        "created_at": _fmt_dt(task.created_at),
    }


async def _safe_run(task_id: str) -> None:
    """包裹 run_research，吞掉顶层异常（内部已经把 task 置 FAILED）。"""
    try:
        await run_research(task_id)
    except Exception as e:
        print(f"[ERROR] research task {task_id} crashed: {e}")
        traceback.print_exc()


# ============================================================
# 轮询任务
# ============================================================

@router.get("/research/{task_id}", summary="查询任务状态")
async def get_research(task_id: str):
    task = get_task_store().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    return _task_to_response(task)


# ============================================================
# 列表
# ============================================================

@router.get("/researches", summary="列出最近任务")
async def list_researches(limit: int = 20):
    tasks = get_task_store().list_tasks(limit=limit)
    return {
        "count": len(tasks),
        "tasks": [_task_to_summary(t) for t in tasks],
    }


# ============================================================
# 健康检查
# ============================================================

@router.get("/", summary="健康检查")
async def root():
    return {
        "name": "深度研究助手",
        "version": "0.1.0",
        "docs": "/docs",
    }


# ============================================================
# 响应格式化
# ============================================================

def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _task_to_response(task: ResearchTask) -> dict:
    """把内部 ResearchTask 转成 API 响应（扁平化 report）。"""
    out: dict = {
        "task_id": task.task_id,
        "topic": task.topic,
        "status": task.status.value,
        "progress": task.progress,
        "created_at": _fmt_dt(task.created_at),
        "updated_at": _fmt_dt(task.updated_at),
    }
    if task.finished_at is not None:
        out["finished_at"] = _fmt_dt(task.finished_at)
    if task.error:
        out["error"] = task.error
    if task.report is not None:
        out["report_markdown"] = task.report.markdown
        out["sources"] = [s.model_dump() for s in task.report.sources]
        if task.report.confidence_notes:
            out["confidence_notes"] = task.report.confidence_notes
    if task.process is not None:
        out["process"] = task.process.model_dump()
    return out


def _task_to_summary(task: ResearchTask) -> dict:
    return {
        "task_id": task.task_id,
        "topic": task.topic,
        "status": task.status.value,
        "progress": task.progress,
        "created_at": _fmt_dt(task.created_at),
    }
