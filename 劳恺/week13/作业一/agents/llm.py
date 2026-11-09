"""LCEL 链工厂：统一模型、端点、温度与提示词装配。

显式传 base_url，不依赖 openai SDK 读取 OPENAI_BASE_URL 的行为；
API key 仍由 openai SDK 从 OPENAI_API_KEY 环境变量读取。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable, Type

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
import os
from ..config import settings


@lru_cache(maxsize=None)
def build_chat_model(model: str, temperature: float) -> ChatOpenAI:
    """按 (模型, 温度) 复用客户端。"""

    return ChatOpenAI(
        model=model,
        base_url=settings.base_url,
        temperature=temperature,
        api_key=os.getenv("DEEPSEEK_API_KEY"),
    )


def structured_chat_model(
    model: str,
    *,
    temperature: float,
    schema: Type[BaseModel],
    method: str = "function_calling",
    tool_choice: str = "auto",
) -> Runnable:
    """返回强制输出 `schema` 结构化结果的 Runnable。

    两处都必须显式指定，否则连不上 DeepSeek：

    1. `method="function_calling"`：langchain-openai 1.4 的默认值是 `json_schema`，
       会发送 `response_format={"type": "json_schema"}`，DeepSeek 不支持，
       报 `400 This response_format type is unavailable now`。
    2. `tool_choice="auto"`：默认会强制指定函数名，而 deepseek-flash 是思考模式
       模型，报 `400 Thinking mode does not support this tool_choice`。
       langchain-openai 把 `**kwargs` 展开在默认的 `tool_choice` 之后，
       所以这里传的值会覆盖掉强制函数名。
    """

    return build_chat_model(model, temperature).with_structured_output(
        schema, method=method, tool_choice=tool_choice
    )


class _LazyRunnable(Runnable):
    """首次调用时才构建内部链。

    ChatOpenAI 在**构造时**就校验 OPENAI_API_KEY，而 Agent 是模块级对象、
    在导入时创建。若立即构造，仅 `import sql_agent` 就需要 API key，
    单测也会被迫设置假 key。推迟到第一次调用，既保持模块级单例，
    又让测试无需真实凭证，缺失 key 时仍在首次调用处明确报错。
    """

    def __init__(self, factory: Callable[[], Runnable]) -> None:
        self._factory = factory
        self._delegate: Runnable | None = None

    def _resolve(self) -> Runnable:
        if self._delegate is None:
            self._delegate = self._factory()
        return self._delegate

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return self._resolve().invoke(input, config=config, **kwargs)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return await self._resolve().ainvoke(input, config=config, **kwargs)


def build_structured_chain(
    *,
    instructions: str,
    model: str,
    temperature: float,
    schema: Type[BaseModel],
) -> Runnable:
    """`system + human 提示词 | 结构化输出模型`，输入 {"prompt": ...}。"""

    def factory() -> Runnable:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", instructions),
                ("human", "{prompt}"),
            ]
        )
        return prompt | structured_chat_model(
            model, temperature=temperature, schema=schema
        )

    return _LazyRunnable(factory)
