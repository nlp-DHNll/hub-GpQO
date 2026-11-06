"""测试辅助：构建带 tool_calls 的 AIMessage，便于 validate_selection 解析。"""

from langchain_core.messages import AIMessage

from sql_agent.models import (
    FinalAnswer,
    SQLDraft,
    TableSelection,
)


def make_table_selection_msg(sel: TableSelection) -> AIMessage:
    """构建包含 TableSelection tool_call 的 AIMessage。"""
    msg = AIMessage(content="")
    msg.tool_calls = [
        {
            "name": "TableSelection",
            "args": sel.model_dump(),
            "id": "call_test_sel",
        }
    ]
    return msg


def make_sql_draft_msg(draft: SQLDraft) -> AIMessage:
    """构建包含 SQLDraft tool_call 的 AIMessage。"""
    msg = AIMessage(content="")
    msg.tool_calls = [
        {
            "name": "SQLDraft",
            "args": draft.model_dump(),
            "id": "call_test_sql",
        }
    ]
    return msg


def make_final_answer_msg(answer: FinalAnswer) -> AIMessage:
    """构建包含 FinalAnswer tool_call 的 AIMessage。"""
    msg = AIMessage(content="")
    msg.tool_calls = [
        {
            "name": "FinalAnswer",
            "args": answer.model_dump(),
            "id": "call_test_fa",
        }
    ]
    return msg
