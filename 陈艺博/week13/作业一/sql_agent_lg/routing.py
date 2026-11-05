"""条件边：把「下一步走哪个节点」写成纯函数，方便单独测试。

LangGraph 的 conditional edge 只负责读状态、返回目标节点名；
真正的业务动作都在节点里，路由函数不调用 LLM、不碰数据库。
"""

from __future__ import annotations

from typing import Literal

from .state import AgentState


def route_after_select(
    state: AgentState,
) -> Literal["select_tables", "load_schema", "clarify"]:
    """选表之后：合法就继续；非法最多再试一次；需要澄清就结束。"""

    selection = state.get("selection")
    if selection is None:
        return "clarify"
    if selection.needs_clarification or not selection.tables:
        return "clarify"

    # selection_feedback 非空说明上一次选表非法（表不存在 / 不连通）。
    if state.get("selection_feedback"):
        if state.get("selection_attempts", 0) < 2:
            return "select_tables"
        return "clarify"
    return "load_schema"


def route_after_validate(
    state: AgentState,
) -> Literal["execute_sql", "rewrite_sql", "fail"]:
    """校验之后：通过就执行；失败且还有预算就改写，否则失败收尾。"""

    validation = state.get("validation")
    if validation is not None and validation.ok:
        return "execute_sql"
    if state.get("repair_attempts", 0) >= state.get("max_repair_attempts", 3):
        return "fail"
    return "rewrite_sql"


def route_after_execute(
    state: AgentState,
) -> Literal["summarize", "empty_result", "rewrite_sql", "fail"]:
    """执行之后：成功就汇总/判空；失败则和校验失败共享修复预算。"""

    execution = state.get("execution")
    validation = state.get("validation")

    if execution is not None and validation is not None and validation.ok:
        if execution.row_count == 0:
            return "empty_result"
        return "summarize"

    if state.get("repair_attempts", 0) >= state.get("max_repair_attempts", 3):
        return "fail"
    return "rewrite_sql"


def route_after_rewrite(
    state: AgentState,
) -> Literal["validate_sql", "fail"]:
    """改写之后：能修就回到校验；明确修不了就直接失败收尾。"""

    if state.get("failure_kind") == "cannot_fix":
        return "fail"
    return "validate_sql"
