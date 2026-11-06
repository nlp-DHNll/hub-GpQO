"""graph.py — 只做 add_node / add_edge / add_conditional_edges。

返回未 compile 的 StateGraph，compile() 在调用方做（便于测试挂 InMemorySaver）。
"""

from __future__ import annotations

from functools import partial

from langgraph.graph import END, StateGraph

from .agents import Agents
from .db.catalog import SchemaCatalog
from .nodes import (
    clarify_or_reject_node,
    execute_node,
    failure_answer_node,
    schema_render_node,
    sql_generate_node,
    sql_rewrite_node,
    summarize_node,
    table_select_node,
    table_select_tools_node,
    validate_selection_node,
    validate_sql_node,
)
from .routes import (
    route_after_execute,
    route_after_select,
    route_after_validate_selection,
    route_after_validate_sql,
)
from .state import SQLAgentState


def build_graph(
    catalog: SchemaCatalog,
    agents: Agents,
) -> StateGraph:
    """装配所有节点和边。"""
    g = StateGraph(SQLAgentState)

    # LLM 节点（需要 agent）
    g.add_node(
        "table_select",
        partial(table_select_node, catalog=catalog, agent=agents.table_selector),
    )
    g.add_node(
        "sql_generate",
        partial(sql_generate_node, agent=agents.sql_generator),
    )
    g.add_node(
        "sql_rewrite",
        partial(sql_rewrite_node, agent=agents.sql_rewriter),
    )
    g.add_node(
        "summarize",
        partial(summarize_node, agent=agents.summarizer),
    )

    # 确定性节点（需要 catalog）
    g.add_node(
        "table_select_tools",
        partial(table_select_tools_node, catalog=catalog),
    )
    g.add_node(
        "validate_selection",
        partial(validate_selection_node, catalog=catalog),
    )
    g.add_node(
        "schema_render",
        partial(schema_render_node, catalog=catalog),
    )
    g.add_node(
        "validate_sql",
        partial(validate_sql_node, catalog=catalog),
    )
    g.add_node(
        "execute",
        partial(execute_node, catalog=catalog),
    )

    # 终止节点（不需要注入）
    g.add_node("clarify_or_reject", clarify_or_reject_node)
    g.add_node("failure_answer", failure_answer_node)

    # 边
    g.set_entry_point("table_select")

    g.add_conditional_edges("table_select", route_after_select, {
        "table_select_tools": "table_select_tools",
        "validate_selection": "validate_selection",
    })
    g.add_edge("table_select_tools", "table_select")

    g.add_conditional_edges("validate_selection", route_after_validate_selection, {
        "table_select": "table_select",
        "schema_render": "schema_render",
        "clarify_or_reject": "clarify_or_reject",
    })
    g.add_edge("schema_render", "sql_generate")
    g.add_edge("sql_generate", "validate_sql")

    g.add_conditional_edges("validate_sql", route_after_validate_sql, {
        "execute": "execute",
        "sql_rewrite": "sql_rewrite",
        "failure_answer": "failure_answer",
    })
    g.add_edge("sql_rewrite", "validate_sql")

    g.add_conditional_edges("execute", route_after_execute, {
        "summarize": "summarize",
        "sql_rewrite": "sql_rewrite",
        "failure_answer": "failure_answer",
    })

    g.add_edge("summarize", END)
    g.add_edge("clarify_or_reject", END)
    g.add_edge("failure_answer", END)

    return g  # 未 compile，compile() 在调用方做
