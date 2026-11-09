"""LangGraph 图状态：节点之间共享的可序列化数据。

与原来的 ``QueryState`` 不同，这里用 ``TypedDict`` 描述图的 channel：
LangGraph 会把每个节点返回的字段合并进状态，未返回的字段原样保留。
"""

from __future__ import annotations

from typing import TypedDict

from .models import (
    ExecutionResult,
    FinalAnswer,
    SQLAttempt,
    TableSelection,
    ValidationResult,
)


class GraphState(TypedDict, total=False):
    """一次查询在图中流转的完整状态。"""

    question: str
    selection: TableSelection | None
    tables: list[str]
    schema_context: str
    sql: str | None
    attempts: list[SQLAttempt]
    validation: ValidationResult | None
    execution: ExecutionResult | None
    answer: FinalAnswer | None
    repair_attempts: int
    cannot_fix: bool
    cannot_fix_reason: str
    status: str
    error: str | None


def initial_state(question: str) -> GraphState:
    """构造图的入口状态。"""

    return GraphState(
        question=question,
        selection=None,
        tables=[],
        schema_context="",
        sql=None,
        attempts=[],
        validation=None,
        execution=None,
        answer=None,
        repair_attempts=0,
        cannot_fix=False,
        cannot_fix_reason="",
        status="running",
        error=None,
    )
