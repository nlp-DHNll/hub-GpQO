"""LLM 客户端(全节点统一 BASE_MODEL)与结构化输出模型。"""
from langchain_openai import ChatOpenAI

from app.config import settings


def get_llm(temperature: float = 0.2) -> ChatOpenAI:
    """OpenAI 兼容客户端,凭据来自项目根 .env。"""
    return ChatOpenAI(
        model=settings.base_model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=temperature,
    )
