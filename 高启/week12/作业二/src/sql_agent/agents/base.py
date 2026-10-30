"""LangChain 结构化输出 Runnable 的公共构造方法。"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from ..config import settings


@lru_cache(maxsize=8)
def _structured_chain(
    model_name: str,
    temperature: float,
    output_schema: type[BaseModel],
    instructions: str,
):
    """按模型和输出类型缓存可复用的 LangChain Runnable。"""

    model = ChatOpenAI(
        model=model_name,
        base_url=settings.base_url,
        temperature=temperature,
        # DeepSeek 默认开启 Thinking；其 Thinking 模式不接受强制 tool_choice。
        extra_body={"thinking": {"type": "disabled"}},
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", instructions),
            ("human", "{input}"),
        ]
    )
    # DeepSeek 的 OpenAI 兼容接口不支持 response_format=json_schema；
    # 使用工具调用承载 Pydantic 结构化输出。
    return prompt | model.with_structured_output(
        output_schema,
        method="function_calling",
    )


async def invoke_structured(
    *,
    model_name: str,
    temperature: float,
    output_schema: type[BaseModel],
    instructions: str,
    prompt: str,
) -> BaseModel:
    """异步运行结构化输出链，并返回对应的 Pydantic 对象。"""

    chain = _structured_chain(model_name, temperature, output_schema, instructions)
    return await chain.ainvoke({"input": prompt})
