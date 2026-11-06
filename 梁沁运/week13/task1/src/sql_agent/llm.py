"""StructuredAgent — 四个 Agent 共用的 LLM 调用封装。

约定：
- Agent 在模块级定义为 StructuredAgent 实例，不在每次请求时新建。
- 链在首次 ainvoke 时懒构建，导入模块不需要 DEEPSEEK_API_KEY。
- ChatDeepSeek + bind_tools，不用 with_structured_output。
- extra_body={"thinking": {"type": "disabled"}} 强制关闭思考模式。
- 解析顺序：先 tool_calls 参数 → 再回退正文 JSON。
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from .config import get_deepseek_settings, SQL_AGENT_TOOL_CHOICE

if SQL_AGENT_TOOL_CHOICE is None:
    SQL_AGENT_TOOL_CHOICE = "auto"


class StructuredOutputParseError(Exception):
    """结构化输出解析失败，由节点层处理。"""

    def __init__(self, message: str, raw_content: str = ""):
        super().__init__(message)
        self.raw_content = raw_content


class StructuredAgent:
    """对 ChatDeepSeek + bind_tools 的封装。

    output_schema 作为 tool 绑定，LLM 返回 tool_call 携带结构化 JSON。
    """

    def __init__(
        self,
        *,
        name: str,
        output_schema: type[BaseModel],
        system_prompt: str,
        temperature: float = 0.0,
        tools: list[BaseTool] | None = None,
        tool_choice: str | None = None,
    ):
        self.name = name
        self.output_schema = output_schema
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.tools = tools or []
        self._tool_choice = tool_choice or SQL_AGENT_TOOL_CHOICE
        self._chain = None  # 懒构建

    # ------------------------------------------------------------------
    # 懒构建
    # ------------------------------------------------------------------
    def _build_chain(self):
        """首次调用时构建 LLM 链，导入模块不需要 API key。"""
        from langchain_deepseek import ChatDeepSeek

        settings = get_deepseek_settings()
        if not settings.is_configured:
            raise RuntimeError(
                "DEEPSEEK_API_KEY 未设置。请设置环境变量后重试。"
            )

        llm = ChatDeepSeek(
            model=settings.model,
            api_key=settings.api_key,
            api_base=settings.base_url,
            temperature=self.temperature,
            extra_body={"thinking": {"type": "disabled"}},
        )

        # 将 output_schema 作为输出工具绑定
        all_tools = [self.output_schema] + self.tools
        self._chain = llm.bind_tools(all_tools, tool_choice=self._tool_choice)

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------
    def _parse(self, message: AIMessage) -> BaseModel:
        """优先 tool_calls 参数，回退正文 JSON。"""
        # 路径 1：tool_calls
        if message.tool_calls:
            for tc in message.tool_calls:
                if tc["name"] == self.output_schema.__name__:
                    try:
                        return self.output_schema.model_validate(tc["args"])
                    except Exception as exc:
                        raise StructuredOutputParseError(
                            f"tool_call args 解析失败: {exc}",
                            raw_content=str(tc["args"]),
                        ) from exc

        # 路径 2：回退解析正文 JSON（兼容代码块包裹）
        content = (
            message.content if isinstance(message.content, str)
            else str(message.content)
        )
        if content:
            content = content.strip()
            # 尝试提取代码块内的 JSON
            code_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if code_match:
                content = code_match.group(1)
            # 尝试提取裸 JSON 对象
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                try:
                    return self.output_schema.model_validate(
                        json.loads(json_match.group(0))
                    )
                except (json.JSONDecodeError, Exception) as exc:
                    raise StructuredOutputParseError(
                        f"正文 JSON 解析失败: {exc}",
                        raw_content=content[:500],
                    ) from exc

        raise StructuredOutputParseError(
            "AIMessage 中既无匹配的 tool_call 也无可解析的 JSON 正文",
            raw_content=content[:500],
        )

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def build_messages(
        self,
        user_prompt: str,
        history: list[BaseMessage] | None = None,
    ) -> list[BaseMessage]:
        """构建消息列表。首次调用时包含 system + user；重试时复用历史。"""
        if history:
            return list(history)
        return [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_prompt),
        ]

    async def ainvoke(
        self,
        messages: list[BaseMessage],
    ) -> tuple[BaseModel, AIMessage]:
        """调用 LLM 并解析为 output_schema。"""
        if self._chain is None:
            self._build_chain()

        response: AIMessage = await self._chain.ainvoke(messages)
        parsed = self._parse(response)
        return parsed, response
