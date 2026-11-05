"""接口数据结构（Pydantic）。

请求只带最小必要信息；响应把工作流的中间产物（轨迹 / SQL / 表）一并带回，
让前端能把“Agent 怎么想的”透明地展示出来。
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """一次问答请求。"""

    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    api_key: str = Field(..., description="用户自填的 DeepSeek API Key，仅本次请求使用")
    session_id: str = Field(default="", description="会话标识（预留）")


class TraceStep(BaseModel):
    """一条节点轨迹（与 job1 Trace.to_list() 的结构一一对应）。"""

    agent: str = ""
    step: str = ""
    status: str = ""   # ok / warn / fail
    detail: str = ""
    elapsed: float = 0.0


class ChatResponse(BaseModel):
    """一次问答的完整结果。"""

    rejected: bool
    answer: str
    tables: list[str] = []
    sql: str = ""
    rounds: int = 0
    trace: list[TraceStep] = []


class HealthResponse(BaseModel):
    """存活探针响应。"""

    status: str
