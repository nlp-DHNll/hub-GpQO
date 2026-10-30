"""LLM 客户端:OpenAI 兼容 vision 接口(AsyncOpenAI),凭据来自目录链上的 .env。"""
from openai import AsyncOpenAI

from app.config import settings
from app.prompts import RECOGNIZE_PROMPT

# 模块级共享客户端(连接复用);超时由客户端参数控制,到点抛 openai.APITimeoutError(S7)。
# max_retries=0 禁用 SDK 层自动重试:SDK 默认重试 2 次会把 30s 超时放大到 90s+,
# 违反 S7「超时即终止」;解析失败的业务重试由 routes 的 S6 逻辑负责。
_client = AsyncOpenAI(
    api_key=settings.api_key,
    base_url=settings.base_url,
    timeout=settings.llm_timeout,
    max_retries=0,
)


async def recognize_image(data_url: str) -> str:
    """图片识别:base64 data URL → 模型原始文本输出(strip 后)。

    data_url: data:image/jpeg;base64,... 格式(PRD §8 已实测可用)
    temperature=0.0 取确定性分类输出(T8)。
    """
    resp = await _client.chat.completions.create(
        model=settings.base_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": RECOGNIZE_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        temperature=0.0,
    )
    return (resp.choices[0].message.content or "").strip()
