"""执行轨迹记录。

多 Agent 系统最难排查的就是“到底是哪个 Agent 在哪一步做错了”，
所以每个节点的交接点都往 Trace 里记一条：谁、做了什么、耗时多久、结论是什么。

状态只使用 ASCII 的 ok / warn / fail（方便前端直接映射为徽标，
也避免 Windows GBK 控制台打印特殊符号报错）。
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

STATUS_OK = "ok"
STATUS_FAIL = "fail"
STATUS_WARN = "warn"


@dataclass
class TraceEvent:
    """一条轨迹：哪个 Agent，做了什么，耗时与结论。"""

    agent: str
    action: str
    detail: str = ""
    elapsed: float = 0.0
    status: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def line(self, index: int) -> str:
        """渲染成一行控制台文本。"""
        head = f"{index:02d}. {self.agent:<20}{self.action:<14}"
        tail = f"{self.elapsed:6.2f}s"
        parts = [head, tail]
        if self.status:
            parts.append(f"[{self.status.upper()}]")
        if self.detail:
            parts.append(self.detail)
        return "  ".join(parts)


class Trace:
    """收集并按需打印 Agent 执行轨迹。"""

    def __init__(self, echo: bool = True) -> None:
        self.events: list[TraceEvent] = []
        self.echo = echo
        self._start = time.perf_counter()

    # -------------------- 记录 --------------------

    def record(self, agent: str, action: str, detail: str = "",
               status: str = "", elapsed: float = 0.0, **data: Any) -> TraceEvent:
        """追加一条轨迹，echo 打开时立即打印。"""
        event = TraceEvent(agent=agent, action=action, detail=detail,
                           status=status, elapsed=elapsed, data=data)
        self.events.append(event)
        if self.echo:
            print("  " + event.line(len(self.events)))
        return event

    @contextmanager
    def span(self, agent: str, action: str) -> Iterator[dict[str, Any]]:
        """按代码块计时，退出时自动记录。

        用法::

            with trace.span("SqlCriticAgent", "语义审查") as box:
                box["status"] = STATUS_OK
                box["detail"] = "通过"
        """
        box: dict[str, Any] = {}
        started = time.perf_counter()
        try:
            yield box
        finally:
            self.record(
                agent,
                action,
                detail=str(box.get("detail", "")),
                status=str(box.get("status", "")),
                elapsed=time.perf_counter() - started,
            )

    # -------------------- 输出 --------------------

    @property
    def total_elapsed(self) -> float:
        """整条链路的墙钟耗时。"""
        return time.perf_counter() - self._start

    def render(self, title: str = "Agent 执行轨迹") -> str:
        """把全部轨迹渲染成可直接打印的文本块。"""
        if not self.events:
            return f"{title}：（无记录）"
        lines = [f"========== {title} =========="]
        lines.extend(event.line(i) for i, event in enumerate(self.events, 1))
        lines.append(f"合计 {len(self.events)} 步，耗时 {self.total_elapsed:.2f}s")
        return "\n".join(lines)

    def to_list(self) -> list[dict[str, Any]]:
        """导出为可序列化结构（job2 前端直接渲染为轨迹卡）。"""
        return [
            {
                "agent": e.agent,
                "step": e.action,
                "status": e.status,
                "detail": e.detail,
                "elapsed": round(e.elapsed, 3),
            }
            for e in self.events
        ]


def get_trace(config: Any) -> Trace:
    """从 LangGraph 的 RunnableConfig 里取出 Trace。

    由 run_agent 通过 ``config={"configurable": {"trace": trace}}`` 注入；
    取不到时返回一个静默 Trace 兜底，保证节点单独调用也不报错。
    """
    try:
        trace = config["configurable"]["trace"]
        if isinstance(trace, Trace):
            return trace
    except (KeyError, TypeError):
        pass
    return Trace(echo=False)
