"""聊天接口：POST /api/chat。

错误映射（前端据此给出友好提示，不白屏）：
    422 —— 入参不合法（未填 Key / 问题为空）；
    502 —— DeepSeek 拒绝了 Key（无效或过期）；
    429 —— DeepSeek 限流；
    500 —— 其他内部异常（堆栈只进日志，不外泄）。
"""

import logging

from fastapi import APIRouter, HTTPException

from ..schemas import ChatRequest, ChatResponse
from ..service import ApiKeyInvalidError, RateLimitedError, handle_chat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """执行一次 SQL 智能体问答。"""
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空")
    if not req.api_key.strip():
        raise HTTPException(status_code=422, detail="请先填写 API Key")

    try:
        return handle_chat(req)
    except ApiKeyInvalidError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RateLimitedError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:  # 兜底：内部异常只记日志，避免堆栈细节暴露给前端
        logger.exception("SQL Agent 工作流执行失败")
        raise HTTPException(status_code=500, detail="服务开小差了，请稍后重试") from exc
