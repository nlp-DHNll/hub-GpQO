"""将 Agent 的运行事件写入 UTF-8 JSONL 日志。"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

from ..data_models import RunEvent, RunState


def _json_value(value: object) -> str:
    """把日志中的日期、时间和文件路径转换成 JSON 字符串。"""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"日志字段不支持 {type(value).__name__} 类型")


def _log_fields(entry: RunEvent) -> dict[str, object]:
    """根据事件挑选相关字段，避免反复写入整个运行状态。"""
    event, state = entry.event, entry.state
    fields: dict[str, object] = {"event": event}
    if event == "run_initializing":
        fields.update(
            run_id=state.run_id,
            month=state.month,
            started_at=state.started_at.isoformat(timespec="seconds"),
        )
    if event.startswith("run_"):
        fields["status"] = state.status
    if state.step is not None and event not in {"run_succeeded", "run_started"}:
        fields["step"] = state.step.name
        if event == "step_started" and state.step.attempt is not None:
            fields["attempt"] = state.step.attempt
        if event in {"step_completed", "step_failed", "step_cancelled"}:
            fields["duration_ms"] = state.step.duration_ms
    if event in {"review_result", "revision_requested", "run_succeeded", "run_failed", "run_cancelled"}:
        fields["repair_round"] = state.repair_round
    if entry.level != "INFO":
        fields["level"] = entry.level
    if entry.details:
        fields["details"] = entry.details
    return fields


class RunLogger:
    """为一次运行保存日志，写入后可将同一条事件交给命令行显示。"""

    def __init__(
        self,
        path: Path,
        get_state: Callable[[], RunState],
        *,
        on_event: Callable[[RunEvent], None] | None = None,
    ) -> None:
        self.path = path
        self._get_state = get_state
        self._on_event = on_event
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=False)  # 每次运行独享日志，保护已有文件。

    def record(
        self,
        event: str,
        *,
        level: str = "INFO",
        details: dict[str, object] | None = None,
    ) -> RunEvent:
        """获取当前状态，每次调用追加一条事件。"""
        entry = RunEvent(
            event=event,
            state=self._get_state(),
            level=level,
            details=dict(details) if details is not None else {},
        )
        line = json.dumps(_log_fields(entry), ensure_ascii=False, default=_json_value)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"{line}\n")
        if self._on_event is not None:
            self._on_event(entry)
        return entry
