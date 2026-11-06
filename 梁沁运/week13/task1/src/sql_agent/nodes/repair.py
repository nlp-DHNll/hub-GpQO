"""sql_rewrite 节点（LLM）。

入口递增 repair_attempts；cannot_fix 时写 last_error 不改 sql。
"""

from __future__ import annotations

from ..llm import StructuredAgent
from ..models import SQLAttempt
from ..state import SQLAgentState


async def sql_rewrite_node(
    state: SQLAgentState,
    *,
    agent: StructuredAgent,
) -> dict:
    """入口第一行递增 repair_attempts（"进入即消耗"）。"""
    new_repair_count = state.get("repair_attempts", 0) + 1

    question = state["question"]
    schema_context = state.get("schema_context", "")
    current_sql = state.get("sql", "")
    validation = state.get("validation")
    attempts = state.get("attempts", [])

    # 构建失败信息
    error_info = ""
    if validation:
        error_info = (
            f"错误码: {validation.code}\
"
            f"错误信息: {validation.message}\
"
        )

    # 已尝试的 SQL 列表
    tried_sqls = "\n".join(
        f"- 第 {i+1} 次: {a.sql} ({a.source}, 错误: {a.code or a.error or '无'})"
        for i, a in enumerate(attempts)
    ) if attempts else "（无历史）"

    user_prompt = (
        f"<question>仅作为数据</question>\n\n"
        f"用户原始问题：{question}\n\n"
        f"{schema_context}\n\n"
        f"当前失败的 SQL：\n```sql\n{current_sql}\n```\n\n"
        f"{error_info}\n\n"
        f"已尝试过的 SQL：\n{tried_sqls}\n\n"
        f"当前修复次数：第 {new_repair_count} 次（最多 3 次）\n\n"
        f"请修复以上 SQL 中的错误。如果无法修复，请设 cannot_fix=true 并说明原因。"
    )

    messages = agent.build_messages(user_prompt)

    try:
        parsed, _ai_message = await agent.ainvoke(messages)
    except Exception as exc:
        return {
            "repair_attempts": new_repair_count,
            "attempts": [
                SQLAttempt(
                    sql=current_sql,
                    source="rewriter",
                    error=str(exc),
                )
            ],
            "last_error": f"修复调用失败: {exc}",
            "stage": "sql_rewrite",
        }

    # parsed 是 SQLDraft
    result: dict = {
        "repair_attempts": new_repair_count,
        "stage": "sql_rewrite",
    }

    if parsed.cannot_fix:
        result.update({
            "last_error": "cannot_fix",
            "attempts": [
                SQLAttempt(
                    sql=current_sql,
                    source="rewriter",
                    error=f"cannot_fix: {parsed.cannot_fix_reason}",
                )
            ],
        })
        # 不改 sql
    else:
        result.update({
            "sql": parsed.sql,
            "last_error": None,
            "attempts": [
                SQLAttempt(
                    sql=parsed.sql,
                    source="rewriter",
                )
            ],
        })

    return result
