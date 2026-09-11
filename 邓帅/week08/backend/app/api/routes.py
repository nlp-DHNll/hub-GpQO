"""研究任务 API:发起 / SSE 进度 / 取消 / 报告查询 + 任务生命周期管理。

任务状态索引:进程内 TASKS dict(状态、事件缓冲、协程句柄);
重启后惰性恢复——请求命中内存没有的 task_id 时查 status.json 与
SQLite checkpoint,未终结任务从断点续跑。
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app import report as report_mod
from app.graph.builder import build_graph
from app.graph.state import initial_state
from app.report import REPORTS_DIR, read_status, write_status

logger = logging.getLogger(__name__)

router = APIRouter()

TERMINAL = {"completed", "incomplete", "aborted", "failed"}


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200)


class TaskEntry:
    """单个研究任务的运行时句柄:状态 + SSE 事件缓冲 + 订阅队列。"""

    def __init__(self, task_id: str, topic: str, status: str = "running"):
        self.task_id = task_id
        self.topic = topic
        self.status = status
        self.events: list[dict] = []
        self.handle: asyncio.Task | None = None
        self._queues: list[asyncio.Queue] = []

    def add_event(self, payload: dict) -> None:
        ev = {"id": len(self.events) + 1, **payload}
        self.events.append(ev)
        for q in self._queues:
            q.put_nowait(ev)

    def subscribe(self) -> asyncio.Queue:
        """新订阅:先重放缓冲,再跟随新事件。"""
        q: asyncio.Queue = asyncio.Queue()
        for ev in self.events:
            q.put_nowait(ev)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._queues:
            self._queues.remove(q)


TASKS: dict[str, TaskEntry] = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------- 后台执行 ----------

async def _run_research(task_id: str, topic: str, checkpointer) -> None:
    """后台研究协程:驱动图执行,custom 事件同步进任务缓冲。"""
    entry = TASKS[task_id]
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": task_id}}
    try:
        async for mode, chunk in graph.astream(
            initial_state(task_id, topic), config, stream_mode=["custom", "updates"]
        ):
            if mode == "custom" and isinstance(chunk, dict):
                entry.add_event(chunk)
    except asyncio.CancelledError:
        entry.status = "aborted"
        write_status(task_id, {
            "task_id": task_id, "topic": topic,
            "status": "aborted", "updated_at": _now(),
        })
        entry.add_event({"type": "aborted", "task_id": task_id})
        raise
    except Exception as e:
        logger.exception("研究任务失败 %s", task_id)
        entry.status = "failed"
        write_status(task_id, {
            "task_id": task_id, "topic": topic, "status": "failed",
            "error": str(e), "updated_at": _now(),
        })
        entry.add_event({"type": "error", "message": str(e), "task_id": task_id})
        return
    # 正常结束:状态以落盘的 process.json 为准(completed / incomplete)
    process = _read_process(task_id)
    entry.status = process.get("status") if process else "completed"
    write_status(task_id, {
        "task_id": task_id, "topic": topic,
        "status": entry.status, "updated_at": _now(),
    })


def _read_process(task_id: str) -> dict:
    p = REPORTS_DIR / task_id / "process.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _checkpointer(request: Request):
    cp = getattr(request.app.state, "checkpointer", None)
    if cp is None:
        raise HTTPException(503, "checkpoint 存储未就绪")
    return cp


async def _resolve_task(request: Request, task_id: str) -> TaskEntry | None:
    """内存命中 → 落盘终结态 → checkpoint 惰性恢复;均无返回 None(404)。"""
    if task_id in TASKS:
        return TASKS[task_id]

    st = read_status(task_id)
    if st and st.get("status") in TERMINAL:
        entry = TaskEntry(task_id, st.get("topic", ""), status=st["status"])
        etype = {"completed": "report_done", "incomplete": "report_done",
                 "aborted": "aborted", "failed": "error"}[st["status"]]
        entry.add_event({"type": etype, "task_id": task_id})
        TASKS[task_id] = entry
        return entry

    # 未终结或无状态文件:查 checkpoint,存在则断点续跑
    cp = _checkpointer(request)
    tup = await cp.aget_tuple({"configurable": {"thread_id": task_id}})
    if tup is None:
        return None
    channel_values = tup.checkpoint.get("channel_values", {})
    topic = channel_values.get("topic", "")
    entry = TaskEntry(task_id, topic, status="running")
    TASKS[task_id] = entry
    write_status(task_id, {
        "task_id": task_id, "topic": topic,
        "status": "running", "updated_at": _now(), "resumed": True,
    })
    entry.add_event({"type": "resumed", "task_id": task_id})

    async def _resume():
        graph = build_graph(checkpointer=cp)
        config = {"configurable": {"thread_id": task_id}}
        try:
            async for mode, chunk in graph.astream(
                None, config, stream_mode=["custom", "updates"]
            ):
                if mode == "custom" and isinstance(chunk, dict):
                    entry.add_event(chunk)
        except asyncio.CancelledError:
            entry.status = "aborted"
            write_status(task_id, {
                "task_id": task_id, "topic": topic,
                "status": "aborted", "updated_at": _now(),
            })
            entry.add_event({"type": "aborted", "task_id": task_id})
            raise
        except Exception as e:
            logger.exception("恢复任务失败 %s", task_id)
            entry.status = "failed"
            write_status(task_id, {
                "task_id": task_id, "topic": topic, "status": "failed",
                "error": str(e), "updated_at": _now(),
            })
            entry.add_event({"type": "error", "message": str(e), "task_id": task_id})
            return
        process = _read_process(task_id)
        entry.status = process.get("status") if process else "completed"
        write_status(task_id, {
            "task_id": task_id, "topic": topic,
            "status": entry.status, "updated_at": _now(),
        })

    entry.handle = asyncio.create_task(_resume())
    return entry


# ---------- 接口 ----------

@router.post("/research")
async def start_research(body: ResearchRequest, request: Request):
    task_id = uuid.uuid4().hex[:12]
    entry = TaskEntry(task_id, body.topic)
    TASKS[task_id] = entry
    write_status(task_id, {
        "task_id": task_id, "topic": body.topic,
        "status": "running", "started_at": _now(),
    })
    entry.add_event({"type": "created", "task_id": task_id, "topic": body.topic})
    entry.handle = asyncio.create_task(
        _run_research(task_id, body.topic, _checkpointer(request))
    )
    return {"task_id": task_id}


@router.get("/research/{task_id}")
async def research_status(task_id: str, request: Request):
    entry = await _resolve_task(request, task_id)
    if entry is None:
        raise HTTPException(404, "任务不存在")
    return {
        "task_id": task_id,
        "topic": entry.topic,
        "status": entry.status,
        "events_count": len(entry.events),
    }


@router.get("/research/{task_id}/events")
async def research_events(
    task_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    entry = await _resolve_task(request, task_id)
    if entry is None:
        raise HTTPException(404, "任务不存在")

    try:
        since = int(last_event_id) if last_event_id else 0
    except ValueError:
        since = 0

    async def gen():
        q = entry.subscribe()
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield {"comment": "keep-alive"}  # 空闲心跳保活
                    continue
                if ev["id"] <= since:
                    continue  # Last-Event-ID 已确认过的事件不重发
                yield {
                    "id": str(ev["id"]),
                    "data": json.dumps(ev, ensure_ascii=False),
                }
                if ev.get("type") in ("report_done", "aborted", "error"):
                    return
        finally:
            entry.unsubscribe(q)

    return EventSourceResponse(gen())


@router.delete("/research/{task_id}")
async def cancel_research(task_id: str, request: Request):
    entry = await _resolve_task(request, task_id)
    if entry is None:
        raise HTTPException(404, "任务不存在")
    if entry.status == "running" and entry.handle and not entry.handle.done():
        entry.handle.cancel()
        return {"task_id": task_id, "status": "cancelling"}
    # 已完结:幂等返回现状,不产生副作用
    return {"task_id": task_id, "status": entry.status}


@router.get("/reports")
async def list_reports():
    items = []
    if REPORTS_DIR.exists():
        for d in sorted(REPORTS_DIR.iterdir(), reverse=True):
            process_file = d / "process.json"
            if not (d.is_dir() and process_file.exists()):
                continue
            try:
                p = json.loads(process_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            items.append({
                "task_id": p.get("task_id", d.name),
                "topic": p.get("topic", ""),
                "created_at": p.get("created_at", ""),
                "status": p.get("status", ""),
                "stats": p.get("stats", {}),
            })
    return {"items": items}


@router.get("/reports/{task_id}")
async def get_report(task_id: str):
    d = REPORTS_DIR / task_id
    report_file = d / "report.md"
    if not report_file.exists():
        raise HTTPException(404, "报告不存在")
    return {
        "task_id": task_id,
        "report_md": report_file.read_text(encoding="utf-8"),
        "process": _read_process(task_id),
    }
