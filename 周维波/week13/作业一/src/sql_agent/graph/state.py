"""LangGraph 状态定义。

状态是节点之间唯一的共享上下文：节点返回“增量”，由图合并；
`stages` 用 operator.add 逐节点累加，供 CLI/网页展示执行时间线。
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from ..models import (
    ExecutionResult,
    FinalAnswer,
    SQLAttempt,
    TableSelection,
    ValidationResult,
    WorkflowOutput,
)


class GraphState(TypedDict, total=False):
    # 输入
    question: str
    max_repair_attempts: int

    # 选表阶段
    selection: TableSelection | None
    select_attempts: int
    select_feedback: str
    select_status: str  # ok / retry / clarify

    # SQL 阶段
    tables: list[str]
    schema_context: str
    sql: str | None
    attempts: list[SQLAttempt]
    validation: ValidationResult | None
    execution: ExecutionResult | None

    # 修复与终止
    repair_attempts: int
    terminal_reason: str | None  # clarify / cannot_fix / exhausted / empty
    terminal_message: str | None

    # 汇总与输出
    answer: FinalAnswer | None
    output: WorkflowOutput | None

    # 执行时间线（节点追加）
    stages: Annotated[list[dict], operator.add]
