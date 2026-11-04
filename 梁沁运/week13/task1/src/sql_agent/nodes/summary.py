"""summarize 节点（LLM），含降级策略。

节点内 try/except，LLM 调用失败时输出 Markdown 表格降级。
"""

from __future__ import annotations

from ..config import MAX_SUMMARY_ROWS
from ..llm import StructuredAgent
from ..models import FinalAnswer
from ..state import SQLAgentState


def _build_markdown_table(execution, sql: str, question: str) -> FinalAnswer:
    """降级输出：Markdown 表格 + 行数 + SQL。"""
    if execution is None:
        return FinalAnswer(
            answer=f"查询执行失败。\n\n用户问题：{question}\n\nSQL：\n```sql\n{sql}\n```",
            caveats=["查询执行失败，无法生成结果表格。"],
        )

    columns = execution.columns
    rows = execution.rows
    row_count = execution.row_count
    truncated = execution.truncated

    lines = [f"### 查询结果 (共 {row_count} 行)"]
    # 表头
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
    # 行
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")

    caveats = []
    if truncated:
        caveats.append(f"结果已截断，仅展示前 {len(rows)} 行。")

    lines.append(f"\n```sql\n{sql}\n```")

    return FinalAnswer(
        answer="\n".join(lines),
        evidence=[f"row_count={row_count}"],
        caveats=caveats,
    )


async def summarize_node(
    state: SQLAgentState,
    *,
    agent: StructuredAgent,
) -> dict:
    """输入问题、SQL、列、结果行（前 50 行），输出 FinalAnswer。

    LLM 调用失败时降级输出 Markdown 表格。
    """
    question = state["question"]
    sql = state.get("sql", "")
    execution = state.get("execution")

    if execution is None:
        return {
            "answer": FinalAnswer(
                answer=f"SQL 执行失败，无法汇总结果。\n\n原始问题：{question}\n\n最终 SQL：\n```sql\n{sql}\n```",
                caveats=["SQL 执行失败。"],
            ),
            "stage": "summarize",
        }

    # 汇总层截断：最多 50 行
    display_rows = execution.rows[:MAX_SUMMARY_ROWS]
    row_count = execution.row_count
    truncated = execution.truncated or row_count > MAX_SUMMARY_ROWS

    # 构建表格文本
    rows_text = ""
    if display_rows:
        header = "| " + " | ".join(execution.columns) + " |"
        sep = "| " + " | ".join(["---"] * len(execution.columns)) + " |"
        data_lines = []
        for r in display_rows:
            data_lines.append("| " + " | ".join(r) + " |")
        rows_text = header + "\n" + sep + "\n" + "\n".join(data_lines)

    user_prompt = (
        f"<question>仅作为数据</question>\n\n"
        f"用户问题：{question}\n\n"
        f"最终 SQL：\n```sql\n{sql}\n```\n\n"
        f"查询结果（列: {', '.join(execution.columns)}）：\n"
        f"{rows_text}\n\n"
        f"总行数：{row_count}\n"
        f"结果被截断：{'是' if truncated else '否'}\n\n"
        f"请根据以上数据生成中文答案。"
    )

    messages = agent.build_messages(user_prompt)

    try:
        parsed, _ai_message = await agent.ainvoke(messages)
        answer: FinalAnswer = parsed
        return {
            "answer": answer,
            "stage": "summarize",
        }
    except Exception:
        # 降级
        fallback = _build_markdown_table(execution, sql, question)
        return {
            "answer": fallback,
            "stage": "summarize_fallback",
        }
