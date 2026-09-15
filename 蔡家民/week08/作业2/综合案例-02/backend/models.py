# -*- coding: utf-8 -*-
"""API、研究过程与持久化使用的 Pydantic 模型。"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Status(str, Enum):
    queued = "queued"
    pending = "pending"
    running = "running"
    cancelling = "cancelling"
    cancelled = "cancelled"
    completed = "completed"
    failed = "failed"


class ResearchDepth(str, Enum):
    quick = "quick"
    standard = "standard"
    deep = "deep"


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=500)
    goal: str = Field("", max_length=2000)
    date_range: str = Field("不限", max_length=100)
    region: str = Field("全球", max_length=100)
    audience: str = Field("业务决策者", max_length=200)
    depth: ResearchDepth = ResearchDepth.standard
    parent_id: str | None = None
    follow_up: str = Field("", max_length=2000)

    @field_validator("topic")
    @classmethod
    def clean_topic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("研究主题不能为空")
        return value


class LoginRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=200)


class SourceRef(BaseModel):
    url: str
    title: str = ""


class JudgeDecision(BaseModel):
    sufficient: bool = False
    reason: str = ""
    new_keywords: list[str] = Field(default_factory=list)


class KeywordOutput(BaseModel):
    keywords: list[str] = Field(..., description="可检索关键词")


class DraftBlock(BaseModel):
    round: int = 0
    keyword: str
    text: str


class ProcessStep(BaseModel):
    type: str
    round: int = 0
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class Conclusion(BaseModel):
    text: str
    sources: list[SourceRef] = Field(default_factory=list)
    is_model_inference: bool = False


class Section(BaseModel):
    heading: str
    body: str
    conclusions: list[Conclusion] = Field(default_factory=list)


class ConfidenceNote(BaseModel):
    overall: Literal["high", "medium", "low"] = "medium"
    info_cutoff: str = ""
    notes: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class ReportContent(BaseModel):
    title: str
    summary: str
    sections: list[Section]
    key_conclusions: list[Conclusion]
    open_questions: list[str] = Field(default_factory=list)


class ReportOutline(BaseModel):
    title: str
    summary: str
    key_conclusions: list[Conclusion] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class Source(BaseModel):
    url: str
    title: str = ""
    site_name: str = ""
    snippet: str = ""
    accessed_at: str = ""
    published_at: str = ""
    extraction_status: Literal["full", "summary", "failed"] = "summary"


class ResearchProcess(BaseModel):
    plan: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    reviewed_urls: list[str] = Field(default_factory=list)
    iterations: int = 0
    steps: list[ProcessStep] = Field(default_factory=list)


class UsageCounters(BaseModel):
    searches: int = 0
    model_calls: int = 0
    elapsed_seconds: int = 0


class ResearchLimits(BaseModel):
    max_rounds: int = 2
    max_seconds: int = 360
    max_searches: int = 8
    max_model_calls: int = 15


class ResearchRecord(BaseModel):
    research_id: str
    topic: str
    goal: str = ""
    date_range: str = "不限"
    region: str = "全球"
    audience: str = "业务决策者"
    depth: ResearchDepth = ResearchDepth.standard
    status: Status
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    friendly_error: str | None = None
    report: ReportContent | None = None
    report_html: str = ""
    sources: list[Source] = Field(default_factory=list)
    draft: list[DraftBlock] = Field(default_factory=list)
    process: ResearchProcess | None = None
    confidence: ConfidenceNote | None = None
    progress: int = 0
    current_step: str = "等待执行"
    limits: ResearchLimits = Field(default_factory=ResearchLimits)
    usage: UsageCounters = Field(default_factory=UsageCounters)
    limited: bool = False
    limit_reason: str = ""
    parent_id: str | None = None
    root_id: str | None = None
    version: int = 1
    follow_up: str = ""


class DeepResearchResult(BaseModel):
    report: ReportContent
    report_html: str
    sources: list[Source]
    draft: list[DraftBlock]
    process: ResearchProcess
    confidence: ConfidenceNote
    usage: UsageCounters = Field(default_factory=UsageCounters)
    limited: bool = False
    limit_reason: str = ""


class AdminStats(BaseModel):
    service: str = "ok"
    database: str = "ok"
    redis: str = "unknown"
    total: int = 0
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    searches: int = 0
    model_calls: int = 0


if __name__ == "__main__":
    req = ResearchRequest(topic="  Agent 框架对比  ", depth="standard")
    assert req.topic == "Agent 框架对比"
    rec = ResearchRecord(
        research_id="demo", topic=req.topic, status=Status.queued,
        created_at="2026-09-10T00:00:00+00:00", updated_at="2026-09-10T00:00:00+00:00",
    )
    assert ResearchRecord.model_validate_json(rec.model_dump_json()).research_id == "demo"
    print("models 自检 OK")
