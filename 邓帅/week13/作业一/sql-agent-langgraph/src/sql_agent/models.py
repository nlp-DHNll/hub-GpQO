"""SQL Agent 的 Pydantic 数据契约。

与 week12 版的差异：新增 ChatTurn 与 QueryState.history——多轮对话时，
入口层从 checkpoint 读出上一轮结果组装 history，注入新一轮的图状态，
让选表 / 生成 Agent 能理解追问与指代。
"""

from __future__ import annotations

from enum import Enum

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
    explanation: str = Field("", description="SQL 如何回答用户问题")
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


class ChatTurn(BaseModel):
    """多轮对话中的一轮（含澄清轮），由入口层从 checkpoint 组装。"""

    question: str
    answer: str
    sql: str | None = None
    tables: list[str] = Field(default_factory=list)


class RepairState(BaseModel):
    """修复子图的状态：validate → execute → rewrite 循环。

    子图只关心「把一条 SQL 修到能执行出结果」，与主图的选表/汇总无关；
    输入输出经包装节点与父图状态显式转换（课件 05_子图调用 的写法）。
    """

    question: str
    schema_context: str = ""
    tables: list[str] = Field(default_factory=list)
    sql: str | None = None
    attempts: list[SQLAttempt] = Field(default_factory=list)
    validation: ValidationResult | None = None
    execution: ExecutionResult | None = None
    repair_attempts: int = 0
    stage: str = "repair_init"
    final: WorkflowOutput | None = None


class QueryState(BaseModel):
    """LangGraph 主图状态：一次查询的完整状态。

    与 week12 版的差异：
    - history：多轮对话历史，入口层每轮从 checkpoint 组装注入；
    - validate/execute/rewrite 三节点移入修复子图，主图不再持有循环。
    final（终止路径上组装好的最终输出）语义不变，路由函数据此结束。
    """

    question: str
    history: list[ChatTurn] = Field(default_factory=list)
    selection: TableSelection | None = None
    schema_context: str = ""
    sql: str | None = None
    attempts: list[SQLAttempt] = Field(default_factory=list)
    validation: ValidationResult | None = None
    execution: ExecutionResult | None = None
    answer: FinalAnswer | None = None
    repair_attempts: int = 0
    stage: str = "init"
    final: WorkflowOutput | None = None


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
