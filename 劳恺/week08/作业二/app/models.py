"""数据模型 —— 整个项目的数据契约。

所有跨模块传递的数据结构都在这里定义。修改此处字段时，
需同步检查 researcher / task_store / api / report 各层是否仍兼容。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================
# 枚举
# ============================================================

class TaskStatus(str, Enum):
    """任务生命周期状态。"""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================
# API 输入
# ============================================================

class ResearchRequest(BaseModel):
    """POST /research 请求体。"""
    topic: str = Field(..., min_length=2, max_length=500, description="研究主题")
    max_rounds: Optional[int] = Field(
        None, ge=1, le=10, description="检索轮数上限，覆盖 .env 默认值"
    )
    num_subquestions: Optional[int] = Field(
        None, ge=1, le=10, description="规划阶段拆解的子问题数，覆盖 .env 默认值"
    )


# ============================================================
# 搜索数据
# ============================================================

class SearchResult(BaseModel):
    """单条 Bocha 搜索结果。仅使用 Bocha 返回的 summary，不抓全文。"""
    title: str
    url: str
    summary: str = Field(..., description="Bocha 返回的 summary 字段，作为抽取阶段的事实来源")
    source: Optional[str] = Field(None, description="来源域名，如 '36kr.com'")


class SubQuestion(BaseModel):
    """规划阶段拆出的子问题。"""
    question: str
    rationale: Optional[str] = Field(None, description="为何这个子问题对主题重要")


class SearchRound(BaseModel):
    """一轮检索的完整记录。"""
    round: int = Field(..., ge=1, description="轮次编号，从 1 开始")
    queries: list[str] = Field(default_factory=list, description="本轮发出的所有 query")
    results: list[SearchResult] = Field(default_factory=list, description="本轮获取到的所有结果")
    note: Optional[str] = Field(
        None, description="备注，例如「第 2 轮为信息缺口补检」或「第 1 轮全部失败」"
    )


# ============================================================
# 报告数据
# ============================================================

class Source(BaseModel):
    """最终报告的来源条目。id 用于正文脚注 [n]。"""
    id: int = Field(..., ge=1)
    title: str
    url: str
    snippet: Optional[str] = Field(None, description="该来源的关键句子，便于阅读来源列表时回忆上下文")


class ResearchReport(BaseModel):
    """最终研究报告。"""
    topic: str
    markdown: str = Field(..., description="完整 Markdown 报告，含脚注与置信度标签")
    sources: list[Source] = Field(default_factory=list)
    confidence_notes: Optional[str] = Field(
        None, description="置信度说明文本，例如「第 2 轮检索失败，相关信息缺失」"
    )


# ============================================================
# 过程记录
# ============================================================

class ProcessRecord(BaseModel):
    """研究过程记录，落盘到 data/tasks/{task_id}.json 供回溯。"""
    subquestions: list[SubQuestion] = Field(default_factory=list)
    rounds: list[SearchRound] = Field(default_factory=list)
    duration_seconds: Optional[float] = None
    total_results: int = 0
    tokens_used: Optional[int] = None


# ============================================================
# 任务状态（内部 + API 输出的统一结构）
# ============================================================

class ResearchTask(BaseModel):
    """一个研究任务的完整状态。"""
    task_id: str = Field(..., description="UUID4")
    topic: str
    status: TaskStatus
    progress: Optional[str] = Field(
        None, description="人类可读的进度描述，如「第 1 轮检索中 (2/3 子问题已完成)」"
    )
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None
    error: Optional[str] = Field(None, description="失败时的错误信息")
    request: ResearchRequest
    report: Optional[ResearchReport] = None
    process: Optional[ProcessRecord] = None

    # ---------- 序列化辅助 ----------

    def to_json(self) -> str:
        """序列化为 JSON 字符串，用于落盘。"""
        return self.model_dump_json(indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str) -> "ResearchTask":
        """从 JSON 字符串反序列化。"""
        return cls.model_validate_json(data)
