"""业务服务：桥接 week13/job1 的 LangGraph 工作流。

每个请求独立构建图（独立只读 SQLite 连接 + 独立模型客户端），
避免跨线程共享连接带来的并发问题；chinook 库很小，解析开销可接受。

API Key 由前端随请求传入，服务端不做存储。
"""

import sys
from pathlib import Path

# 引入 week13/job1 的 sql_agent 包（不改动 job1 代码）
JOB1_DIR = Path(__file__).resolve().parents[2].parent / "job1"
if str(JOB1_DIR) not in sys.path:
    sys.path.insert(0, str(JOB1_DIR))

from openai import AuthenticationError, RateLimitError  # noqa: E402
from sql_agent import run_agent  # noqa: E402

from .schemas import ChatRequest, ChatResponse, TraceStep


class ApiKeyInvalidError(Exception):
    """DeepSeek 拒绝了该 API Key（401/403）。"""


class RateLimitedError(Exception):
    """DeepSeek 限流（429）。"""


def handle_chat(req: ChatRequest) -> ChatResponse:
    """运行一次 SQL Agent 工作流并包装成响应结构。"""
    try:
        result = run_agent(question=req.question, api_key=req.api_key, echo=False)
    except AuthenticationError as exc:
        raise ApiKeyInvalidError(f"API Key 无效或已过期，请检查后重试：{exc}") from exc
    except RateLimitError as exc:
        raise RateLimitedError(f"请求过于频繁，请稍后重试：{exc}") from exc

    return ChatResponse(
        rejected=bool(result.get("rejected")),
        answer=str(result.get("answer") or ""),
        tables=list(result.get("tables") or []),
        sql=str(result.get("sql") or ""),
        rounds=int(result.get("rounds") or 0),
        trace=[TraceStep(**step) for step in (result.get("trace") or [])],
    )
