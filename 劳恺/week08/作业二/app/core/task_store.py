"""任务状态管理 —— 内存 dict + JSON 文件落盘。

设计要点：
- 内存 dict 用于 FastAPI 快速读写。
- JSON 文件持久化到 data/tasks/{task_id}.json，重启后可恢复。
- 报告 Markdown 单独存到 data/reports/{task_id}.md，方便直接打开。
- 写盘采用「临时文件 + 原子 rename」防止崩溃导致半截 JSON。
- update_task 是 async + asyncio.Lock，避免同一任务被并发修改覆盖。
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.models import ResearchRequest, ResearchTask, TaskStatus


class TaskNotFoundError(KeyError):
    """指定 task_id 不存在。"""


class TaskStore:
    """任务存储：内存 + JSON 双层。"""

    def __init__(self, data_dir: str | None = None) -> None:
        self.data_dir = Path(data_dir or os.getenv("DATA_DIR", "./data"))
        self.tasks_dir = self.data_dir / "tasks"
        self.reports_dir = self.data_dir / "reports"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self._tasks: dict[str, ResearchTask] = {}
        self._lock = asyncio.Lock()
        self._load_from_disk()

    # ---------- 启动恢复 ----------

    def _load_from_disk(self) -> None:
        """启动时把磁盘上的任务恢复到内存。失败的任务文件静默跳过。"""
        if not self.tasks_dir.exists():
            return
        for path in self.tasks_dir.glob("*.json"):
            try:
                task = ResearchTask.from_json(path.read_text(encoding="utf-8"))
                self._tasks[task.task_id] = task
            except Exception:
                # 损坏的任务文件：跳过，不影响其他任务
                continue

    # ---------- 公开 API ----------

    def create_task(self, request: ResearchRequest) -> ResearchTask:
        """创建新任务，状态 QUEUED，立即落盘。"""
        now = datetime.now()
        task = ResearchTask(
            task_id=str(uuid.uuid4()),
            topic=request.topic,
            status=TaskStatus.QUEUED,
            progress="已入队，等待开始",
            created_at=now,
            updated_at=now,
            request=request,
        )
        self._tasks[task.task_id] = task
        self._persist(task)
        return task

    def get_task(self, task_id: str) -> Optional[ResearchTask]:
        """根据 task_id 查询任务。不存在返回 None。"""
        return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 20) -> list[ResearchTask]:
        """返回最近 N 个任务，按 created_at 倒序。"""
        tasks = sorted(
            self._tasks.values(), key=lambda t: t.created_at, reverse=True
        )
        return tasks[:limit]

    async def update_task(
        self,
        task_id: str,
        *,
        status: Optional[TaskStatus] = None,
        progress: Optional[str] = None,
        error: Optional[str] = None,
        report=None,
        process=None,
    ) -> ResearchTask:
        """更新任务字段（仅更新传入的非 None 字段）。

        若 status 变为 COMPLETED / FAILED 且尚未 finished_at，自动填上。
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(task_id)

            data = task.model_dump()
            now = datetime.now()
            data["updated_at"] = now

            if status is not None:
                data["status"] = status
                if status in (TaskStatus.COMPLETED, TaskStatus.FAILED) and not data.get(
                    "finished_at"
                ):
                    data["finished_at"] = now
            if progress is not None:
                data["progress"] = progress
            if error is not None:
                data["error"] = error
            if report is not None:
                data["report"] = report.model_dump()
            if process is not None:
                data["process"] = process.model_dump()

            new_task = ResearchTask.model_validate(data)
            self._tasks[task_id] = new_task
            self._persist(new_task)
            return new_task

    def save_report_markdown(self, task_id: str, markdown: str) -> Path:
        """把最终报告 Markdown 写到 data/reports/{task_id}.md，返回路径。"""
        path = self.reports_dir / f"{task_id}.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    # ---------- 内部 ----------

    def _persist(self, task: ResearchTask) -> None:
        """原子写入：先写 .tmp，再 rename，避免崩溃产生半截 JSON。"""
        path = self.tasks_dir / f"{task.task_id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(task.to_json(), encoding="utf-8")
        tmp.replace(path)


# ---------- 单例 ----------

_store: TaskStore | None = None


def get_task_store() -> TaskStore:
    """获取全局单例 TaskStore。"""
    global _store
    if _store is None:
        _store = TaskStore()
    return _store
