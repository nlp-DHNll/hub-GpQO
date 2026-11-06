"""StateGraph 装配：节点、条件边与重试预算。

流程图（与原 openai-agents 版状态机等价）：

    START -> select_tables -[ok]------------> build_schema -> generate_sql
                 |  ^                                            |
                 |  └──[retry]                                    v
                 └──────[clarify]--------------------------> validate_sql
                                                                  |  ^
                                                        [ok]      |  | [rewrite]
                                                                  v  |
                                                             execute_sql
                                                          [rows>0] |  | [error]
                                                                  v  |
                                                             summarize  |
                                                          [rows=0] |    |
                                                                  v    |
                                                               finalize <--[budget]
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..db.catalog import SchemaCatalog
from ..db.executor import SQLExecutor
from ..db.validator import SQLValidator
from .nodes import SQLAgentNodes
from .state import GraphState


def route_after_select(state: GraphState) -> Literal["select_tables", "build_schema", "finalize"]:
    status = state.get("select_status") or "clarify"
    if status == "retry":
        return "select_tables"
    if status == "ok":
        return "build_schema"
    return "finalize"


def _budget_left(state: GraphState) -> bool:
    return state.get("repair_attempts", 0) < state.get("max_repair_attempts", 0)


def route_after_validate(state: GraphState) -> Literal["execute_sql", "rewrite_sql", "mark_exhausted"]:
    validation = state.get("validation")
    if validation is not None and validation.ok:
        return "execute_sql"
    return "rewrite_sql" if _budget_left(state) else "mark_exhausted"


def route_after_execute(state: GraphState) -> Literal["summarize", "finalize", "rewrite_sql", "mark_exhausted"]:
    execution = state.get("execution")
    if execution is not None:
        # 空结果已在 execute_sql 节点内给出确定性答案，直接组装输出。
        return "summarize" if execution.row_count > 0 else "finalize"
    return "rewrite_sql" if _budget_left(state) else "mark_exhausted"


def route_after_rewrite(state: GraphState) -> Literal["validate_sql", "finalize"]:
    return "finalize" if state.get("terminal_reason") == "cannot_fix" else "validate_sql"


def build_sql_agent_graph(
    *,
    catalog: SchemaCatalog,
    validator: SQLValidator,
    executor: SQLExecutor,
) -> CompiledStateGraph:
    """构建并编译图；确定性组件通过闭包注入节点，不放进图状态。"""

    nodes = SQLAgentNodes(catalog=catalog, validator=validator, executor=executor)

    builder = StateGraph(GraphState)
    builder.add_node("select_tables", nodes.select_tables)
    builder.add_node("build_schema", nodes.build_schema)
    builder.add_node("generate_sql", nodes.generate_sql)
    builder.add_node("validate_sql", nodes.validate_sql)
    builder.add_node("execute_sql", nodes.execute_sql)
    builder.add_node("rewrite_sql", nodes.rewrite_sql)
    builder.add_node("mark_exhausted", nodes.mark_exhausted)
    builder.add_node("summarize", nodes.summarize)
    builder.add_node("finalize", nodes.finalize)

    builder.add_edge(START, "select_tables")
    builder.add_conditional_edges(
        "select_tables",
        route_after_select,
        {
            "select_tables": "select_tables",
            "build_schema": "build_schema",
            "finalize": "finalize",
        },
    )
    builder.add_edge("build_schema", "generate_sql")
    builder.add_edge("generate_sql", "validate_sql")
    builder.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {
            "execute_sql": "execute_sql",
            "rewrite_sql": "rewrite_sql",
            "mark_exhausted": "mark_exhausted",
        },
    )
    builder.add_conditional_edges(
        "execute_sql",
        route_after_execute,
        {
            "summarize": "summarize",
            "finalize": "finalize",
            "rewrite_sql": "rewrite_sql",
            "mark_exhausted": "mark_exhausted",
        },
    )
    builder.add_conditional_edges(
        "rewrite_sql",
        route_after_rewrite,
        {"validate_sql": "validate_sql", "finalize": "finalize"},
    )
    builder.add_edge("mark_exhausted", "finalize")
    builder.add_edge("summarize", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()
