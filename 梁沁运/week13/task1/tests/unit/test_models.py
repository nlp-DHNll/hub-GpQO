"""test_models.py — Pydantic 契约验证。"""

import pytest

from sql_agent.models import (
    ErrorCode,
    ExecutionResult,
    FinalAnswer,
    SQLAttempt,
    SQLDraft,
    TableSelection,
    ValidationResult,
)


class TestSQLDraft:

    def test_valid_generation(self):
        draft = SQLDraft(
            sql="SELECT * FROM albums",
            explanation="查询所有专辑",
            assumptions=["albums 表存在"],
        )
        assert draft.sql == "SELECT * FROM albums"
        assert not draft.cannot_fix

    def test_cannot_fix_without_sql(self):
        draft = SQLDraft(
            cannot_fix=True,
            cannot_fix_reason="数据库中没有相关表",
        )
        assert draft.cannot_fix
        assert draft.sql == ""

    def test_cannot_fix_with_sql_raises(self):
        with pytest.raises(ValueError, match="cannot_fix=true 时不应提供 sql"):
            SQLDraft(
                sql="SELECT 1",
                cannot_fix=True,
                cannot_fix_reason="test",
            )

    def test_cannot_fix_without_reason_raises(self):
        with pytest.raises(ValueError, match="cannot_fix=true 时必须说明原因"):
            SQLDraft(cannot_fix=True)

    def test_normal_without_sql_raises(self):
        with pytest.raises(ValueError, match="cannot_fix=false 时必须提供 sql"):
            SQLDraft(sql="")


class TestTableSelection:

    def test_valid_selection(self):
        sel = TableSelection(
            tables=["albums", "artists"],
            reason="需要专辑和艺人信息",
            confidence=0.9,
        )
        assert len(sel.tables) == 2
        assert not sel.needs_clarification

    def test_clarification_needed(self):
        sel = TableSelection(
            tables=[],
            reason="问题模糊",
            confidence=0.0,
            needs_clarification=True,
            clarification_question="您想查询哪个艺人的专辑？",
        )
        assert sel.needs_clarification
        assert sel.clarification_question is not None


class TestErrorCode:

    def test_enum_values(self):
        assert ErrorCode.UNSAFE == "unsafe"
        assert ErrorCode.SYNTAX == "syntax"
        assert ErrorCode.UNKNOWN_OBJECT == "unknown_object"
        assert ErrorCode.AMBIGUOUS == "ambiguous"
        assert ErrorCode.RUNTIME == "runtime"
        assert ErrorCode.TIMEOUT == "timeout"
        assert ErrorCode.EMPTY == "empty"


class TestValidationResult:

    def test_valid_result(self):
        vr = ValidationResult(ok=True, normalized_sql="SELECT 1")
        assert vr.ok
        assert vr.code is None

    def test_failed_result(self):
        vr = ValidationResult(
            ok=False,
            code=ErrorCode.UNSAFE,
            message="检测到写操作",
        )
        assert not vr.ok
        assert vr.code == ErrorCode.UNSAFE


class TestExecutionResult:

    def test_basic_result(self):
        er = ExecutionResult(
            columns=["id", "name"],
            rows=[["1", "Alice"], ["2", "Bob"]],
            row_count=2,
        )
        assert er.row_count == 2
        assert not er.truncated


class TestSQLAttempt:

    def test_generator_attempt(self):
        a = SQLAttempt(sql="SELECT * FROM albums", source="generator")
        assert a.source == "generator"
        assert a.code is None

    def test_rewriter_attempt_with_error(self):
        a = SQLAttempt(
            sql="SELECT * FROM albums",
            source="rewriter",
            code=ErrorCode.SYNTAX,
            error="语法错误",
        )
        assert a.source == "rewriter"
        assert a.code == ErrorCode.SYNTAX


class TestFinalAnswer:

    def test_basic_answer(self):
        fa = FinalAnswer(
            answer="共有 347 张专辑。",
            evidence=["row_count=347"],
        )
        assert "347" in fa.answer

    def test_empty_result_answer(self):
        fa = FinalAnswer(
            answer="未查询到符合条件的数据。",
            caveats=["查询结果为空"],
        )
        assert "未查询到" in fa.answer
