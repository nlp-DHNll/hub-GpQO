"""LangGraph 的状态定义。

状态就是「一张便签」：每个节点读它、返回自己的增量更新，边函数根据它决定下一步。
``events`` 用 ``operator.add`` 做 reducer，因此每个节点只需要返回「本次新增的事件」，
LangGraph 会自动把整条执行轨迹累加起来，前端据此展示执行过程。
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from .models import (
    ExecutionResult,
    FinalAnswer,
    SQLAttempt,
    TableSelection,
    ValidationResult,
    WorkflowOutput,
)


class GraphEvent(TypedDict, total=False):
    """一个可展示给前端的阶段事件。"""

    node: str
    label: str
    status: Literal["running", "ok", "warning", "error"]
    detail: str
    elapsed_ms: int
    sql: str


class AgentState(TypedDict, total=False):
    """SQL Agent 图的完整状态。"""

    # ---- 输入 ----
    question: str
    max_repair_attempts: int

    # ---- 选表 ----
    selection: TableSelection | None
    tables: list[str]
    selection_feedback: str
    selection_attempts: int

    # ---- 生成与校验 ----
    schema_context: str
    sql: str | None
    attempts: list[SQLAttempt]
    validation: ValidationResult | None

    # ---- 执行与汇总 ----
    execution: ExecutionResult | None
    final: FinalAnswer | None
    repair_attempts: int

    # ---- 终态 ----
    answer: str | None
    error: str | None
    failure_kind: Literal["repair_exhausted", "cannot_fix", "unexpected"] | None
    failure_message: str
    output: WorkflowOutput | None
    stage: str

    # ---- 执行轨迹（reducer 累加）----
    events: Annotated[list[GraphEvent], operator.add]
