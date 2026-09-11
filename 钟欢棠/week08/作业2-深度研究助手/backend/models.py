# -*- coding: utf-8 -*-
"""研究请求 / 四类产物 / 多 agent 中间结果的 Pydantic 模型。

- report / report_html  结构化报告（标题、摘要、分节正文、关键结论、遗留问题）+ HTML
- sources               来源列表（每条结论关联 URL / 标题，可追溯）
- process               研究过程记录（检索关键词、已读页面、迭代轮数、逐步结果）
- confidence            置信度说明（可靠程度、信息截止时间；无来源结论标注"模型推断"）
- draft                 报告正文草稿（每关键词一段，直接累积成正文）
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Status(str, Enum):
    """研究任务状态机。"""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class ResearchRequest(BaseModel):
    """发起一次研究的请求体。"""

    topic: str = Field(..., min_length=1, max_length=500, description="研究主题")


class SourceRef(BaseModel):
    """一条结论关联的一个来源引用。"""

    url: str
    title: str = ""


class KeywordOutput(BaseModel):
    """关键词 agent 的输出。"""

    keywords: list[str] = Field(..., description="可检索关键词")


class JudgeDecision(BaseModel):
    """判断 agent 的决策（中间产物）。"""

    sufficient: bool = False  # 是否已足够，无需补检
    reason: str = ""
    new_keywords: list[str] = []  # 不足时需要补充检索的新关键词


class DraftBlock(BaseModel):
    """一个关键词检索内容总结出的报告正文段落。"""

    round: int = 0  # 所属检索轮次
    keyword: str  # 对应检索关键词
    text: str  # 总结出的正文文字


class ProcessStep(BaseModel):
    """研究过程中一步的中间结果记录。"""

    type: str  # plan / search / summarize / judge
    round: int = 0
    detail: dict[str, Any] = {}


class Conclusion(BaseModel):
    """单条结论。"""

    text: str
    sources: list[SourceRef] = []
    # 无任何来源支撑、属于"模型推断"的结论为 True
    is_model_inference: bool = False


class Section(BaseModel):
    """报告的一个分节。"""

    heading: str
    body: str
    conclusions: list[Conclusion] = []


class ConfidenceNote(BaseModel):
    """置信度说明。"""

    overall: str = "medium"  # high / medium / low
    info_cutoff: str = ""  # 信息截止时间
    notes: list[str] = []


class ReportContent(BaseModel):
    """结构化报告正文。"""

    title: str
    summary: str
    sections: list[Section]
    key_conclusions: list[Conclusion]
    open_questions: list[str] = []


class ReportOutline(BaseModel):
    """ReportAgent 第一次调用输出的报告元信息（正文分节由草稿直接映射，不走 LLM）。"""

    title: str
    summary: str
    key_conclusions: list[Conclusion] = []
    open_questions: list[str] = []


class Source(BaseModel):
    """来源列表条目（落盘用）。"""

    url: str
    title: str = ""
    site_name: str = ""
    snippet: str = ""
    accessed_at: str = ""


class ResearchProcess(BaseModel):
    """研究过程记录。"""

    plan: list[str] = []  # 初始关键词（规划）
    search_queries: list[str] = []  # 全部检索过的关键词
    reviewed_urls: list[str] = []  # 实际使用的来源 URL
    iterations: int = 0  # 检索/判断轮数
    steps: list[ProcessStep] = []  # 每步中间结果


class ResearchRecord(BaseModel):
    """最终落盘 / 返回的完整对象。"""

    research_id: str
    topic: str
    status: Status
    created_at: str
    updated_at: str
    error: str | None = None
    report: ReportContent | None = None
    report_html: str = ""
    sources: list[Source] = []
    draft: list[DraftBlock] = []
    process: ResearchProcess | None = None
    confidence: ConfidenceNote | None = None


class DeepResearchResult(BaseModel):
    """DeepResearch.run() 返回的完整结果。"""

    report: ReportContent
    report_html: str
    sources: list[Source]
    draft: list[DraftBlock]
    process: ResearchProcess
    confidence: ConfidenceNote


if __name__ == "__main__":
    # 本地自检：构造一条完整记录，验证序列化 -> 反序列化
    req = ResearchRequest(topic="竞品分析：2026 年主流 Agent 框架")
    print("ResearchRequest:", req.model_dump())

    rec = ResearchRecord(
        research_id="demo-id",
        topic=req.topic,
        status=Status.running,
        created_at="2026-09-10T00:00:00+00:00",
        updated_at="2026-09-10T00:00:00+00:00",
        report=ReportContent(
            title="示例报告",
            summary="摘要",
            sections=[Section(heading="背景", body="正文", conclusions=[Conclusion(text="模型推断结论", is_model_inference=True)])],
            key_conclusions=[Conclusion(text="结论", sources=[SourceRef(url="https://example.com", title="示例")])],
        ),
        sources=[Source(url="https://example.com", title="示例")],
        draft=[DraftBlock(round=1, keyword="Agent 框架", text="正文段落")],
        process=ResearchProcess(plan=["Agent 框架"], iterations=1),
        confidence=ConfidenceNote(overall="low", info_cutoff="2026-09-10"),
    )
    dumped = rec.model_dump_json(indent=2, ensure_ascii=False)
    assert len(dumped) > 100
    back = ResearchRecord.model_validate_json(dumped)
    assert back.research_id == "demo-id" and back.status == Status.running
    print("ResearchRecord 序列化 -> 反序列化 OK，字段数 =", len(back.model_dump()))
    print("models 自检 OK")
