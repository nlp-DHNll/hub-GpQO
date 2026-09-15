"""DeepSeek LLM 封装 —— LangChain ChatModel + 重试。

设计要点：
- DeepSeek 使用 OpenAI 兼容接口，所以用 langchain_openai.ChatOpenAI。
- 提供两个入口：chat()（纯文本）和 chat_json()（结构化 JSON）。
- 重试逻辑：指数退避 1s/2s/4s，封装在内部 _with_retry 中。
- 单例 client：避免每次调用都新建 httpx 连接。
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, TypeVar
import re
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel


T = TypeVar("T")


class DeepSeekError(Exception):
    """DeepSeek 调用失败且重试耗尽后抛出。"""


class DeepSeekClient:
    """DeepSeek LLM 客户端（基于 LangChain ChatOpenAI）。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        # self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY", "")
        self.base_url = "https://api.minimaxi.com/v1"
        # self.base_url = base_url or os.getenv(
        #     "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
        # )
        # self.model = "deepseek-v4-flash"
        self.model = "MiniMax-M3"
        self.timeout =  60
        self.max_retries = 3

        if not self.api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY 未设置，请在 .env 中填入"
            )

        self._llm = ChatOpenAI(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
            temperature=0.7,
            extra_body={
                "thinking": {"type": "disabled"},
            },
            # response_format={"type": "json_object"}  # 强制 JSON 输出
        )
    #
    # ---------- 公开 API ----------

    async def chat(
        self,
        user_message: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """简单对话，返回纯文本响应。"""
        messages = self._build_messages(user_message, system)
        response = await self._with_retry(
            self._invoke, messages, temperature=temperature
        )
        return response.content if isinstance(response.content, str) else str(response.content)

    async def chat_json(
        self,
        user_message: str,
        *,
        system: str | None = None,
        schema: type[BaseModel] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any] | BaseModel:
        """对话并解析为 JSON。

        若提供 schema（Pydantic 类），返回校验后的实例；
        否则返回 dict。
        """
        json_instruction = ("""你是一个结构化数据输出系统。
你必须严格只输出合法的 JSON 对象，禁止输出任何解释、思考过程、markdown 标记或其他文字。

输出格式要求：
{
  "sub_questions": [
    {
      "question": "子问题内容",
      "dimension": "维度名称"
    }
  ]
}

示例输入：为什么天空是蓝色的
示例输出：
{"sub_questions": [{"question": "太阳光中不同波长的光在大气中的散射特性是什么", "dimension": "物理原理"}]}

直接输出 JSON，不要有任何其他内容。"""
        )
        full_system = (system or "") + json_instruction

        messages = self._build_messages(user_message, full_system)
        response = await self._with_retry(
            self._invoke, messages, temperature=temperature
        )
        raw = response.content if isinstance(response.content, str) else str(response.content)
        data = self._parse_json(raw)

        if schema is not None:
            return schema.model_validate(data)
        return data

    # ---------- 内部 ----------

    @staticmethod
    def _build_messages(user_message: str, system: str | None) -> list:
        msgs: list = []
        if system:
            msgs.append(SystemMessage(content=system))
        msgs.append(HumanMessage(content=user_message))
        return msgs

    async def _invoke(self, messages: list, *, temperature: float | None):
        if temperature is None:
            return await self._llm.ainvoke(messages)
        # 用临时 temperature
        llm = self._llm.bind(temperature=temperature)
        return await llm.ainvoke(messages)

    async def _with_retry(self, fn, *args, **kwargs):
        """指数退避重试：1s / 2s / 4s。"""
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 —— 上层统一处理
                last_error = e
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    await asyncio.sleep(wait)
        raise DeepSeekError(
            f"DeepSeek 调用失败，已重试 {self.max_retries} 次：{last_error}"
        ) from last_error

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = raw.strip()

        # 先尝试去掉 markdown 代码块
        if text.startswith("```"):
            lines = text.splitlines()
            inner = lines[1:]
            if inner and inner[-1].strip().startswith("```"):
                inner = inner[:-1]
            text = "\n".join(inner).strip()

        # 如果直接解析失败，尝试从文本中提取 JSON 块
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # 尝试用正则提取最外层的 { ... } 或 [ ... ]
            match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass

            raise DeepSeekError(
                f"LLM 输出无法解析为 JSON：{e}\n原文：{raw[:500]}"
            ) from e


# ---------- 单例 ----------

_client: DeepSeekClient | None = None


def get_deepseek() -> DeepSeekClient:
    """获取全局单例 DeepSeekClient。"""
    global _client
    if _client is None:
        _client = DeepSeekClient()
    return _client
