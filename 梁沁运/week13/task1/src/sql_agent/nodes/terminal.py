"""终止节点：clarify_or_reject / failure_answer（v1 简单路径，不引入 interrupt）。"""

from __future__ import annotations

from ..models import FinalAnswer
from ..state import SQLAgentState


async def clarify_or_reject_node(state: SQLAgentState) -> dict:
    """需要澄清或拒绝时终止流程。"""
    sel = state.get("selection")
    last_error = state.get("last_error", "")

    if sel and sel.needs_clarification and sel.clarification_question:
        answer_text = f"需要澄清：{sel.clarification_question}"
    elif last_error:
        # 预算耗尽或无法处理
        selection_count = state.get("selection_retry_count", 0)
        answer_text = (
            f"无法完成表选择（已重试 {selection_count} 次）。"
            f"请提供更明确的问题。"
        )
    else:
        answer_text = "无法理解该问题，请重新描述。"

    return {
        "answer": FinalAnswer(
            answer=answer_text,
            evidence=[],
            caveats=["选表阶段终止，请提供更明确的问题。"],
        ),
        "stage": "clarify_or_reject",
    }


async def failure_answer_node(state: SQLAgentState) -> dict:
    """超预算或 cannot_fix 时终止。"""
    validation = state.get("validation")
    attempts = state.get("attempts", [])
    repair_count = state.get("repair_attempts", 0)
    last_error = state.get("last_error", "")

    # 收集失败原因
    errors: list[str] = []
    if validation and not validation.ok:
        errors.append(f"[{validation.code}] {validation.message}" if validation.code else validation.message)
    if last_error:
        errors.append(last_error)

    error_summary = "\n".join(errors) if errors else "未知错误"

    if last_error == "cannot_fix":
        reason = "模型判定无法修复当前 SQL。"
    else:
        reason = f"修复预算耗尽（已尝试 {repair_count} 次）。"

    # 最后一次 SQL
    last_sql = ""
    if attempts:
        last_sql = attempts[-1].sql

    answer_text = (
        f"### 查询失败\n\n"
        f"**原因**：{reason}\n\n"
        f"**错误信息**：\n{error_summary}\n\n"
        f"**最终 SQL**：\n```sql\n{last_sql}\n```\n\n"
        f"**建议**：请检查问题描述是否与数据库数据匹配，或尝试更简单的查询。"
    )

    return {
        "answer": FinalAnswer(
            answer=answer_text,
            evidence=[],
            caveats=[
                f"repair_attempts={repair_count}",
                f"last_error={last_error}",
            ],
        ),
        "stage": "failure_answer",
    }
