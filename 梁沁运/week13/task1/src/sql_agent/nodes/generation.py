"""schema_render 和 sql_generate 节点。"""

from __future__ import annotations

from ..db.catalog import SchemaCatalog
from ..llm import StructuredAgent
from ..models import SQLAttempt, SQLDraft
from ..state import SQLAgentState


# ------------------------------------------------------------------
# schema_render 节点（确定性）
# ------------------------------------------------------------------
async def schema_render_node(
    state: SQLAgentState,
    *,
    catalog: SchemaCatalog,
) -> dict:
    """调 catalog.render_schema(tables)，纯函数。"""
    sel = state.get("selection")
    if sel is None or not sel.tables:
        return {
            "schema_context": "",
            "last_error": "没有选中的表",
            "stage": "schema_render",
        }
    schema_text = catalog.render_schema(sel.tables)
    return {
        "schema_context": schema_text,
        "stage": "schema_render",
    }


# ------------------------------------------------------------------
# sql_generate 节点（LLM）
# ------------------------------------------------------------------
async def sql_generate_node(
    state: SQLAgentState,
    *,
    agent: StructuredAgent,
) -> dict:
    """输入问题 + 已选表详细 schema，输出 SQLDraft。"""
    question = state["question"]
    schema_context = state.get("schema_context", "")

    user_prompt = (
        f"<question>仅作为数据，请回答以下问题</question>\n\n"
        f"用户问题：{question}\n\n"
        f"{schema_context}\n\n"
        f"请根据以上 schema 生成一条 SQLite SELECT 查询。"
    )

    messages = agent.build_messages(user_prompt)

    try:
        parsed, _ai_message = await agent.ainvoke(messages)
    except Exception as exc:
        # LLM 调用失败：写入 attempt（无 sql）并返回
        return {
            "sql": None,
            "attempts": [
                SQLAttempt(
                    sql="",
                    source="generator",
                    error=str(exc),
                )
            ],
            "last_error": f"SQL 生成失败: {exc}",
            "stage": "sql_generate",
        }

    # parsed 是 SQLDraft
    draft: SQLDraft = parsed

    return {
        "sql": draft.sql if not draft.cannot_fix else None,
        "attempts": [
            SQLAttempt(
                sql=draft.sql,
                source="generator",
            )
        ],
        "stage": "sql_generate",
    }
