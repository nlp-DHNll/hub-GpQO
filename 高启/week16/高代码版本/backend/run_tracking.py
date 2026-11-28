"""记录整次运行的状态、单步耗时和终态。"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic_ns
from uuid import uuid4

from .config import DEFAULT_LOG_DIR
from .data_models import RunEvent, RunResult, RunState, StepState
from .enums import RunStatus, StepName, StepStatus
from .errors import RunFailure
from .log.run_logger import RunLogger


def _elapsed_ms(started_ns: int) -> int:
    """用单调时钟计算耗时，避免系统时钟调整影响结果。"""
    return (monotonic_ns() - started_ns) // 1_000_000


def _failure_message(error: BaseException) -> str:
    if isinstance(error, KeyboardInterrupt):
        return "用户中断运行"
    if isinstance(error, RunFailure):
        return str(error)
    return f"执行时发生 {type(error).__name__}"


class AgentRun:
    """保存本次 Agent 状态，为每个执行步骤记录开始和结束。"""

    def __init__(
        self,
        month: str,
        log_dir: Path,
        on_event: Callable[[RunEvent], None] | None,
    ) -> None:
        self._state = RunState(
            run_id=uuid4().hex,
            month=month,
            status=RunStatus.INITIALIZING,
            started_at=datetime.now(UTC),
        )
        self.logger = RunLogger(
            log_dir / f"{self.state.run_id}.jsonl",
            lambda: self.state,
            on_event=on_event,
        )

    @property
    def state(self) -> RunState:
        """返回当前快照，状态变化时会替换为一个新的快照。"""
        return self._state

    @contextmanager
    def step(
        self,
        name: StepName,
        *,
        attempt: int | None = None,
        repair_round: int | None = None,
    ) -> Iterator[RunLogger]:
        """执行一个步骤，记录其状态，并提供同一个日志实例。"""
        started_ns = monotonic_ns()
        previous_round = self.state.repair_round
        step = StepState(name, StepStatus.RUNNING, attempt=attempt)
        self._state = replace(
            self.state,
            step=step,
            repair_round=self.state.repair_round if repair_round is None else repair_round,
        )
        try:
            self.logger.record("step_started")
            yield self.logger
        except (Exception, KeyboardInterrupt) as error:
            cancelled = isinstance(error, KeyboardInterrupt)
            status = StepStatus.CANCELLED if cancelled else StepStatus.FAILED
            self._finish_step(step, status, started_ns)
            self._state = replace(self.state, repair_round=previous_round)
            self.logger.record(
                f"step_{status}",
                level="WARNING" if cancelled else "ERROR",
            )
            raise
        else:
            self._finish_step(step, StepStatus.COMPLETED, started_ns)
            self.logger.record("step_completed")

    def _finish_step(self, step: StepState, status: StepStatus, started_ns: int) -> None:
        finished = replace(
            step,
            status=status,
            duration_ms=_elapsed_ms(started_ns),
        )
        self._state = replace(self.state, step=finished)

    def _start(self) -> None:
        self.logger.record("run_initializing")
        self._state = replace(self.state, status=RunStatus.RUNNING)
        self.logger.record("run_started")

    def _finish(
        self,
        status: RunStatus,
        *,
        report_path: Path | None = None,
        error: BaseException | None = None,
    ) -> RunResult:
        self._state = replace(self.state, status=status)
        if error is None:
            message = "报告已保存"
            self.logger.record("run_succeeded", details={"report_path": report_path})
        else:
            message = _failure_message(error)
            self.logger.record(
                f"run_{status}",
                level="WARNING" if status is RunStatus.CANCELLED else "ERROR",
                details={"error_type": type(error).__name__, "message": message},
            )
        return RunResult(self.state, self.logger.path, report_path, message)


def run_with_logging(
    month: str,
    execute: Callable[[AgentRun], Path],
    *,
    log_dir: Path = DEFAULT_LOG_DIR,
    on_event: Callable[[RunEvent], None] | None = None,
) -> RunResult:
    """运行一段 Agent 流程，返回最终状态、日志路径和可用的报告路径。"""
    run = AgentRun(month, log_dir, on_event)
    try:
        run._start()
        report_path = execute(run)
        if not report_path.is_file():
            raise RunFailure("报告文件未保存")
    except KeyboardInterrupt as error:
        return run._finish(RunStatus.CANCELLED, error=error)
    except Exception as error:  # noqa: BLE001
        # 运行边界为意外错误保留终态，步骤上下文已记录出错位置。
        return run._finish(RunStatus.FAILED, error=error)
    return run._finish(RunStatus.SUCCEEDED, report_path=report_path)
