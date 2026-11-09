"""SQL Agent 的 Pydantic 数据契约。"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field


class TableSelection(BaseModel):
    """表选择 Agent 的结构化结果。"""

    tables: list[str] = Field(description="回答该问题所需的最少表名集合")
    reason: str = Field(description="选择这些表的理由")
    confidence: float = Field(default=0.0, ge=0, le=1)
    needs_clarification: bool = False
    clarification_question: str | None = None


class SQLDraft(BaseModel):
    """SQL 生成 / 改写 Agent 的结构化结果。"""

    sql: str = Field(description="单条 SQLite SELECT 或 WITH ... SELECT 语句")
    explanation: str = Field(default="", description="SQL 如何回答用户问题")
    assumptions: list[str] = Field(default_factory=list)
    cannot_fix: bool = Field(default=False, description="改写时是否无法修复")


class ErrorCode(str, Enum):
    UNSAFE = "unsafe"
    SYNTAX = "syntax"
    UNKNOWN_OBJECT = "unknown_object"
    AMBIGUOUS = "ambiguous"
    RUNTIME = "runtime"
    TIMEOUT = "timeout"
    EMPTY = "empty"


class ValidationResult(BaseModel):
    ok: bool
    code: ErrorCode | None = None
    message: str = ""
    normalized_sql: str = ""


class ExecutionResult(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False


class SQLAttempt(BaseModel):
    sql: str
    source: str
    code: ErrorCode | None = None
    error: str = ""


class FinalAnswer(BaseModel):
    """结果汇总 Agent 的结构化结果。"""

    answer: str = Field(description="面向用户的自然语言答案")
    evidence: list[str] = Field(default_factory=list, description="支撑答案的具体数值")
    caveats: list[str] = Field(default_factory=list)


class ConversationTurn(BaseModel):
    """对话历史里的一轮，供追问时补上下文。"""

    question: str
    answer: str = ""
    sql: str | None = None
    tables: list[str] = Field(default_factory=list)


class WorkflowOutput(BaseModel):
    """面向用户的最终 JSON 结构，由代码组装。"""

    question: str
    answer: str
    sql: str | None = None
    tables: list[str] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    repair_attempts: int = 0
    evidence: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    error: str | None = None
    # 终态：completed / needs_clarification / cannot_fix / repair_exhausted / failed
    status: str = "completed"
    # 结果集：让前端能直接渲染表格，不必去解析 answer 里的 Markdown
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


def merge_attempts(
    left: list[SQLAttempt], right: list[SQLAttempt]
) -> list[SQLAttempt]:
    """LangGraph reducer：合并 SQL 尝试记录。

    节点只返回本次要写入的记录，由 LangGraph 调用本函数与已有状态合并：

    - sql 相同 -> 视为同一次尝试，用新记录覆盖
      （校验节点先写入，执行节点失败后再把错误码补上）；
    - sql 不同 -> 追加到末尾。
    """

    merged = list(left)
    for item in right:
        if merged and merged[-1].sql == item.sql:
            merged[-1] = item
        else:
            merged.append(item)
    return merged


class QueryState(BaseModel):
    """一次查询的完整状态，同时作为 LangGraph 的 State。

    节点之间只通过这个对象通信：每个节点读自己需要的字段，干完活返回要更新的
    字段，LangGraph 负责把更新合并回状态。

    status 取值：

    - running：流程正常推进中；
    - needs_clarification：选表阶段无法确定表，需要用户澄清；
    - cannot_fix：改写 Agent 判定当前数据库无法回答；
    - completed：已产出最终答案。
    """

    question: str

    # 之前的对话轮次（追问时提供上下文；节点不会改写它）
    history: list[ConversationTurn] = Field(default_factory=list)

    # 选表阶段
    selection: TableSelection | None = None
    select_attempts: int = 0
    select_feedback: str = ""

    # SQL 生成与修复阶段
    schema_context: str = ""
    sql: str | None = None
    attempt_source: str = "generator"
    attempts: Annotated[list[SQLAttempt], merge_attempts] = Field(default_factory=list)
    validation: ValidationResult | None = None
    execution: ExecutionResult | None = None
    repair_attempts: int = 0

    # 结果与输出阶段
    answer: FinalAnswer | None = None
    rewrite_explanation: str = ""
    status: str = "running"
    output: WorkflowOutput | None = None
    stage: str = "init"
