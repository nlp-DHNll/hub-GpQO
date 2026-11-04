"""Pydantic 数据契约——所有 Agent 输入/输出 + State 引用的类型。"""

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class TableSelection(BaseModel):
    tables: list[str] = Field(description="回答该问题所需的最少表名集合")
    reason: str = Field(description="选择这些表的理由")
    confidence: float = Field(ge=0, le=1)
    needs_clarification: bool = False
    clarification_question: str | None = None


class SQLDraft(BaseModel):
    sql: str = ""
    explanation: str = ""
    assumptions: list[str] = Field(default_factory=list)
    cannot_fix: bool = False
    cannot_fix_reason: str | None = None

    @model_validator(mode="after")
    def validate_cannot_fix(self):
        if self.cannot_fix:
            if self.sql:
                raise ValueError("cannot_fix=true 时不应提供 sql")
            if not self.cannot_fix_reason:
                raise ValueError("cannot_fix=true 时必须说明原因")
        elif not self.sql:
            raise ValueError("cannot_fix=false 时必须提供 sql")
        return self


class ErrorCode(str, Enum):
    UNSAFE = "unsafe"
    SYNTAX = "syntax"
    UNKNOWN_OBJECT = "unknown_object"
    AMBIGUOUS = "ambiguous"
    RUNTIME = "runtime"
    TIMEOUT = "timeout"
    EMPTY = "empty"  # 结果为空，不是错误


class ValidationResult(BaseModel):
    ok: bool
    code: ErrorCode | None = None
    message: str = ""
    normalized_sql: str = ""


class ExecutionResult(BaseModel):
    columns: list[str]
    rows: list[list[str]]  # 已转字符串、已截断
    row_count: int
    truncated: bool = False


class SQLAttempt(BaseModel):
    sql: str
    source: str  # generator / rewriter
    code: ErrorCode | None = None
    error: str = ""


class FinalAnswer(BaseModel):
    answer: str
    evidence: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
