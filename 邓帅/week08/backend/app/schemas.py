"""各 LLM 节点的结构化输出模型(plan / read / reflect)。"""
from pydantic import BaseModel, Field


class PlanOutput(BaseModel):
    """plan 节点:主题拆解为子问题。"""

    sub_questions: list[str] = Field(..., min_length=3, max_length=6)


class Finding(BaseModel):
    """单条要点:论点 + 原文摘录佐证 + 来源 URL。"""

    point: str
    quote: str = Field(..., description="来源页面原文摘录,不超过 50 字,不得改写")
    url: str


class FindingsOutput(BaseModel):
    """read 节点(逐页):要点抽取结果。"""

    findings: list[Finding]


class SelectOutput(BaseModel):
    """read 节点(轮首):从本轮搜索结果挑选高价值 URL。"""

    urls: list[str] = Field(..., max_length=6)


class ReflectOutput(BaseModel):
    """reflect 节点:审视信息缺口。"""

    sufficient: bool
    gaps: str = ""
    new_queries: list[str] = Field(default_factory=list, max_length=4)
