"""SQL Agent 的 Pydantic 数据契约（与 week11 版本保持一致）。

这些模型同时承担两个职责：
1. LangChain ``with_structured_output`` 的输出 schema，保证模型返回结构化对象；
2. 组件之间传递数据的类型边界，让 workfow 不依赖自由文本。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TableSelection(BaseModel):
    """表选择 Agent 的输出：只需要决定「用哪些表」。"""

    tables: list[str] = Field(description="回答该问题所需的最少表名集合")
    reason: str = Field(default="", description="选择这些表的理由")
    confidence: float = Field(default=0.0, ge=0, le=1)
    needs_clarification: bool = False
    clarification_question: str | None = None


class SQLDraft(BaseModel):
    """SQL 生成 / 改写 Agent 的输出。"""

    sql: str = Field(description="单条 SQLite SELECT 或 WITH ... SELECT 语句")
    explanation: str = Field(default="", description="SQL 如何回答用户问题")
    assumptions: list[str] = Field(default_factory=list)
    cannot_fix: bool = Field(default=False, description="改写时是否无法修复")


class ErrorCode(str, Enum):
    UNSAFE = "unsafe"                    # 非 SELECT / 多语句 / 危险关键字
    SYNTAX = "syntax"                    # 语法错误
    UNKNOWN_OBJECT = "unknown_object"    # 表或列不存在
    AMBIGUOUS = "ambiguous"              # 列名歧义
    RUNTIME = "runtime"                  # 执行期错误
    TIMEOUT = "timeout"
    EMPTY = "empty"                      # 结果为空（不是错误）


class ValidationResult(BaseModel):
    ok: bool
    code: ErrorCode | None = None
    message: str = ""
    normalized_sql: str = ""


class ExecutionResult(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)   # 统一字符串化
    row_count: int = 0
    truncated: bool = False


class SQLAttempt(BaseModel):
    """保留失败历史，改写 Agent 靠它避免重复踩同一个坑。"""

    sql: str
    source: str                          # generator / rewriter
    code: ErrorCode | None = None
    error: str = ""


class FinalAnswer(BaseModel):
    """结果汇总 Agent 的输出。"""

    answer: str = Field(description="面向用户的自然语言答案")
    evidence: list[str] = Field(default_factory=list, description="支撑答案的具体数值")
    caveats: list[str] = Field(default_factory=list)


class QueryState(BaseModel):
    """一次查询的完整状态，由 Orchestrator（workflow.py）维护。"""

    question: str
    selection: TableSelection | None = None
    schema_context: str = ""
    sql: str | None = None
    attempts: list[SQLAttempt] = Field(default_factory=list)
    validation: ValidationResult | None = None
    execution: ExecutionResult | None = None
    answer: FinalAnswer | None = None
    repair_attempts: int = 0
    stage: str = "init"


class WorkflowOutput(BaseModel):
    """面向用户的最终 JSON，由代码组装而不是模型拼接。"""

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
