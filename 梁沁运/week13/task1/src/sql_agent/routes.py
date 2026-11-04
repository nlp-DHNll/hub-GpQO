"""条件边路由函数 —— 只读 State、不写 State，不 import nodes/。"""

from __future__ import annotations

from .config import MAX_REPAIR_ATTEMPTS, MAX_SELECTION_RETRY
from .state import SQLAgentState


def route_after_select(state: SQLAgentState) -> str:
    """判断 table_select 的最后一条消息是否包含非输出 schema 的 tool_calls。

    如果 tool_calls 包含 get_table_schema → table_select_tools。
    如果 tool_calls 仅包含 TableSelection（输出 schema）→ validate_selection。
    """
    messages = state.get("selection_messages", [])
    if not messages:
        return "validate_selection"
    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None)
    if not tool_calls:
        return "validate_selection"
    # 只有非输出 schema 的 tool_call 才进入工具节点
    for tc in tool_calls:
        if tc.get("name") not in ("TableSelection",):
            return "table_select_tools"
    return "validate_selection"


def route_after_validate_selection(state: SQLAgentState) -> str:
    """根据 TableSelection 校验结果路由。"""
    sel = state.get("selection")
    if sel and sel.needs_clarification:
        return "clarify_or_reject"
    if sel and sel.tables and not state.get("last_error"):
        return "schema_render"
    if state.get("selection_retry_count", 0) < MAX_SELECTION_RETRY:
        return "table_select"
    return "clarify_or_reject"


def route_after_validate_sql(state: SQLAgentState) -> str:
    """校验成功 → execute；cannot_fix → failure_answer；预算内 → sql_rewrite。"""
    validation = state.get("validation")
    if validation and validation.ok:
        return "execute"
    if state.get("last_error") == "cannot_fix":
        return "failure_answer"
    if state.get("repair_attempts", 0) < MAX_REPAIR_ATTEMPTS:
        return "sql_rewrite"
    return "failure_answer"


def route_after_execute(state: SQLAgentState) -> str:
    """执行成功 → summarize；cannot_fix → failure_answer；预算内 → sql_rewrite。"""
    if state.get("execution") is not None:
        return "summarize"
    if state.get("last_error") == "cannot_fix":
        return "failure_answer"
    if state.get("repair_attempts", 0) < MAX_REPAIR_ATTEMPTS:
        return "sql_rewrite"
    return "failure_answer"
