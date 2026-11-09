"""Web API 的 Pydantic 契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class StandaloneQuestion(BaseModel):
    """多轮追问改写器的输出。"""

    question: str = Field(description="改写后可独立执行的数据库查询问题")
    rewritten: bool = Field(default=False, description="是否真的改写了")
    reason: str = Field(default="", description="改写理由，一句话")


class ChatResponse(BaseModel):
    ok: bool = True
    question: str
    standalone_question: str | None = None
    followup_reason: str | None = None
    answer: str
    sql: str | None = None
    tables: list[str] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    repair_attempts: int = 0
    evidence: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    error: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    elapsed_ms: int = 0
