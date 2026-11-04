"""SQLAgentState — LangGraph StateGraph 的状态契约。"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage

from .models import (
    TableSelection,
    SQLAttempt,
    ValidationResult,
    ExecutionResult,
    FinalAnswer,
)


class SQLAgentState(TypedDict, total=False):
    # 输入
    question: str

    # 选表子循环（路径 B：消息驱动工具调用）
    selection_messages: Annotated[list[AnyMessage], add_messages]
    selection: TableSelection | None
    selection_retry_count: int  # 独立预算，上限 MAX_SELECTION_RETRY

    # 生成 / 修复
    schema_context: str
    sql: str | None
    attempts: Annotated[list[SQLAttempt], operator.add]
    repair_attempts: int  # 共享预算，上限 MAX_REPAIR_ATTEMPTS

    # 校验 / 执行 / 汇总
    validation: ValidationResult | None
    execution: ExecutionResult | None
    answer: FinalAnswer | None

    # 可观测性（仅日志，不参与路由）
    stage: str
    last_error: str | None
