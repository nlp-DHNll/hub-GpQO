"""M3: test_routes.py — 路由函数穷举所有分支含 cannot_fix 短路。"""

import pytest

from sql_agent.models import (
    ErrorCode,
    ExecutionResult,
    FinalAnswer,
    SQLAttempt,
    TableSelection,
    ValidationResult,
)
from sql_agent.routes import (
    MAX_REPAIR_ATTEMPTS,
    MAX_SELECTION_RETRY,
    route_after_execute,
    route_after_select,
    route_after_validate_selection,
    route_after_validate_sql,
)


# ------------------------------------------------------------------
# route_after_select
# ------------------------------------------------------------------
class TestRouteAfterSelect:

    def test_empty_messages_goes_to_validate(self):
        state = {"selection_messages": []}
        assert route_after_select(state) == "validate_selection"

    def test_message_without_tool_calls(self):
        from langchain_core.messages import AIMessage
        state = {"selection_messages": [AIMessage(content="我需要 albums 表")]}
        assert route_after_select(state) == "validate_selection"

    def test_message_with_tool_calls(self):
        from langchain_core.messages import AIMessage
        msg = AIMessage(content="")
        msg.tool_calls = [{"name": "get_table_schema", "args": {"table": "albums"}, "id": "1"}]
        state = {"selection_messages": [msg]}
        assert route_after_select(state) == "table_select_tools"


# ------------------------------------------------------------------
# route_after_validate_selection
# ------------------------------------------------------------------
class TestRouteAfterValidateSelection:

    def test_legal_selection(self):
        sel = TableSelection(tables=["albums"], reason="", confidence=1.0)
        state = {"selection": sel}
        assert route_after_validate_selection(state) == "schema_render"

    def test_needs_clarification(self):
        sel = TableSelection(
            tables=[], reason="", confidence=0.0,
            needs_clarification=True, clarification_question="what?",
        )
        state = {"selection": sel}
        assert route_after_validate_selection(state) == "clarify_or_reject"

    def test_null_selection_with_retry_budget(self):
        state = {"selection": None, "selection_retry_count": 0, "last_error": "failed"}
        assert route_after_validate_selection(state) == "table_select"

    def test_null_selection_budget_exhausted(self):
        state = {
            "selection": None,
            "selection_retry_count": MAX_SELECTION_RETRY,
            "last_error": "failed",
        }
        assert route_after_validate_selection(state) == "clarify_or_reject"


# ------------------------------------------------------------------
# route_after_validate_sql
# ------------------------------------------------------------------
class TestRouteAfterValidateSQL:

    def test_ok_goes_to_execute(self):
        state = {"validation": ValidationResult(ok=True)}
        assert route_after_validate_sql(state) == "execute"

    def test_cannot_fix_short_circuits(self):
        state = {
            "validation": ValidationResult(ok=False),
            "last_error": "cannot_fix",
            "repair_attempts": 0,  # 预算充足但 can't fix 短路
        }
        assert route_after_validate_sql(state) == "failure_answer"

    def test_within_budget(self):
        state = {
            "validation": ValidationResult(ok=False),
            "repair_attempts": 0,
        }
        assert route_after_validate_sql(state) == "sql_rewrite"

    def test_budget_exhausted(self):
        state = {
            "validation": ValidationResult(ok=False),
            "repair_attempts": MAX_REPAIR_ATTEMPTS,
        }
        assert route_after_validate_sql(state) == "failure_answer"

    def test_no_validation_goes_to_rewrite(self):
        state = {"repair_attempts": 0}
        assert route_after_validate_sql(state) == "sql_rewrite"


# ------------------------------------------------------------------
# route_after_execute
# ------------------------------------------------------------------
class TestRouteAfterExecute:

    def test_success_goes_to_summarize(self):
        state = {
            "execution": ExecutionResult(
                columns=["c"], rows=[["1"]], row_count=1
            ),
        }
        assert route_after_execute(state) == "summarize"

    def test_cannot_fix_short_circuits(self):
        state = {
            "execution": None,
            "last_error": "cannot_fix",
            "repair_attempts": 0,
        }
        assert route_after_execute(state) == "failure_answer"

    def test_failure_within_budget(self):
        state = {
            "execution": None,
            "repair_attempts": 0,
        }
        assert route_after_execute(state) == "sql_rewrite"

    def test_failure_budget_exhausted(self):
        state = {
            "execution": None,
            "repair_attempts": MAX_REPAIR_ATTEMPTS,
        }
        assert route_after_execute(state) == "failure_answer"
