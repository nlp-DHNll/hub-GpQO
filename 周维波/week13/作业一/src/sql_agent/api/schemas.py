"""HTTP 接口的数据契约。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import WorkflowOutput


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000, description="自然语言问题")


class QueryResponse(BaseModel):
    output: WorkflowOutput
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    stages: list[dict] = Field(default_factory=list)
    elapsed_ms: float = 0.0
