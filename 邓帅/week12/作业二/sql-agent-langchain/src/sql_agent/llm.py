"""ChatOpenAI 工厂：对应 openai-agents 版在 agents/__init__.py 里的模型接线。

显式传入 api_key / base_url（来自 .env 或环境变量），不依赖 SDK 的
隐式环境变量读取，方便测试与多环境部署。
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from .config import settings


def make_llm(*, model: str, temperature: float) -> ChatOpenAI:
    """按配置构建一个 Chat Completions 兼容的聊天模型。

    兼容端点（DashScope / DeepSeek / 私有化 MaaS）对 OpenAI
    Responses API 与 json_schema response_format 的支持参差不齐，
    结构化输出统一走 function calling（见各 agent 模块）。
    """

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=settings.api_key,
        base_url=settings.base_url,
    )
