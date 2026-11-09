"""大模型构建工具：统一 DeepSeek 的接入方式。

DeepSeek 兼容 OpenAI 协议，因此直接用 langchain-openai 的 ChatOpenAI；
json_mode 走 DeepSeek 支持的 ``response_format={"type": "json_object"}``，
不要用 json_schema（DeepSeek 不支持，会直接报 400）。
"""

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    LLM_MAX_RETRIES,
    TEMPERATURE,
)


def build_chat_model(api_key: str | None = None, json_mode: bool = False) -> BaseChatModel:
    """构建 DeepSeek 聊天模型。

    api_key 优先级：运行时传入（job2 前端）> 环境变量 > config.py 占位。
    注意：ChatOpenAI 构建时不发网络请求，Key 是否有效要到第一次调用才暴露。
    """
    key = (api_key or DEEPSEEK_API_KEY or "").strip()
    if not key or key == "your_api_key":
        raise RuntimeError(
            "未配置 DEEPSEEK_API_KEY：请设置同名环境变量、"
            "在 config.py 的占位处填写，或调用时传入 api_key 参数"
        )

    model = ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=key,
        base_url=DEEPSEEK_BASE_URL,
        temperature=TEMPERATURE,
        max_retries=LLM_MAX_RETRIES,
        timeout=60,
    )
    return model.bind(response_format={"type": "json_object"}) if json_mode else model
