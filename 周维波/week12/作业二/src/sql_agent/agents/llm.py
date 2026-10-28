"""LangChain 模型工厂：按 (model, temperature) 缓存，等价于模块级 Agent 的复用语义。

原 openai-agents 版在模块级定义 Agent(model=...)（构造不校验 API Key）。
ChatOpenAI 构造时需要 API Key（langchain-openai 1.x 会直接抛错），
因此这里提供懒加载工厂：导入包 / 跑测试不需要 Key，首次真正调用链时才校验。
"""

from __future__ import annotations

import os
from functools import lru_cache

from langchain_openai import ChatOpenAI

from ..config import settings


def _api_key() -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError(
            "缺少 OPENAI_API_KEY。请先设置环境变量，再调用 LLM 链"
            "（导入包、运行测试不需要 Key）。"
        )
    return key


@lru_cache(maxsize=8)
def get_chat_model(model: str, temperature: float) -> ChatOpenAI:
    """进程级单例 ChatOpenAI；同一 (model, temperature) 只建一次客户端。"""

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        base_url=settings.base_url,
        api_key=_api_key(),
        timeout=60,
        max_retries=1,
    )
