"""LangChain 接入层：把「四个 Agent」收敛成一个可复用的调用单元。

对应关系（与 week11 的 openai-agents 版本一一对应）：

| openai-agents                     | 本文件 / LangChain                              |
| --------------------------------- | ----------------------------------------------- |
| ``Agent(instructions=..., output_type=M)`` | ``ChatPromptTemplate | ChatOpenAI.with_structured_output(M)`` |
| ``Runner.run(agent, prompt)``     | ``await Chain.ainvoke({"input": prompt})``       |
| ``ModelSettings(temperature=...)``| ``ChatOpenAI(temperature=...)``                  |
| ``trace("SQLAgentWorkflow")``     | LangSmith 环境变量开关（见 README）              |

之所以再包一层 ``StructuredAgent``，是为了：

* 让 workflow 只依赖「给文本、拿 Pydantic 对象」这一个接口，
  测试时可以塞假实现，不需要 monkeypatch LangChain；
* 把重试、超时、日志、错误类型转换集中在一处，workflow 里不出现 SDK 细节。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from .config import Settings, settings as default_settings

logger = logging.getLogger(__name__)


class LLMNotConfigured(RuntimeError):
    """缺少 API Key 或模型不可用。"""


class AgentInvocationError(RuntimeError):
    """Agent 调用失败：网络、限流、结构化输出解析失败等。"""


def build_chat_model(
    *,
    model: str,
    temperature: float = 0.0,
    settings: Settings | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """构造一个 OpenAI 兼容协议的聊天模型（DashScope / DeepSeek / OpenAI 通用）。"""

    cfg = settings or default_settings
    api_key = cfg.api_key
    if not api_key:
        envs = " 或 ".join(cfg.api_key_envs)
        raise LLMNotConfigured(
            f"未配置 API Key。请在项目根目录 .env 中填写 {envs}，"
            f"并确认 SQL_AGENT_BASE_URL={cfg.base_url}"
        )

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=cfg.base_url,
        temperature=temperature,
        timeout=cfg.request_timeout,
        max_retries=cfg.max_retries,
        **kwargs,
    )


class StructuredAgent:
    """一个 Agent = 系统提示词 + 模型 + 输出 schema，对外只有 ``ainvoke``。"""

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        output_schema: type[BaseModel],
        model: str,
        temperature: float = 0.0,
        settings: Settings | None = None,
        structured_method: str | None = None,
        chat_model: BaseChatModel | None = None,
    ) -> None:
        self.name = name
        self.output_schema = output_schema
        self.model_name = model
        cfg = settings or default_settings
        method = structured_method or cfg.structured_method

        # chat_model 只在测试里注入（假模型），生产路径永远走 build_chat_model。
        chat_model = chat_model or build_chat_model(
            model=model, temperature=temperature, settings=cfg
        )
        # with_structured_output 负责把 schema 变成 function/tool 定义，
        # 再把模型返回的 JSON 反序列化成 Pydantic 对象。
        structured: Runnable = chat_model.with_structured_output(
            output_schema, method=method  # type: ignore[arg-type]
        )
        prompt = ChatPromptTemplate.from_messages(
            [("system", system_prompt), ("human", "{input}")]
        )
        self._chain: Runnable = prompt | structured

    def build_prompt(self, user_input: str) -> dict[str, str]:
        """留给测试/调试：看看实际喂给模型的是什么。"""

        return {"input": user_input}

    async def ainvoke(self, user_input: str) -> BaseModel:
        started = time.perf_counter()
        try:
            raw = await self._chain.ainvoke(self.build_prompt(user_input))
        except Exception as exc:  # noqa: BLE001 - 统一转成业务异常
            raise AgentInvocationError(f"{self.name} 调用失败：{exc}") from exc

        result = self._coerce(raw)
        prompt_chars = len(user_input)
        logger.info(
            "stage=llm_call agent=%s model=%s prompt_chars=%d elapsed=%.2fs",
            self.name,
            self.model_name,
            prompt_chars,
            time.perf_counter() - started,
        )
        return result

    def _coerce(self, raw: Any) -> BaseModel:
        """结构化输出偶尔会退回 dict（依 provider 而定），这里统一兜住。"""

        if isinstance(raw, self.output_schema):
            return raw
        if isinstance(raw, dict):
            try:
                return self.output_schema.model_validate(raw)
            except Exception as exc:  # noqa: BLE001
                raise AgentInvocationError(
                    f"{self.name} 返回的结构不符合 {self.output_schema.__name__}：{exc}"
                ) from exc
        raise AgentInvocationError(
            f"{self.name} 返回了非预期的类型：{type(raw).__name__}"
        )

    async def ainvoke_many(self, inputs: Sequence[str]) -> list[BaseModel]:
        """顺序调用多个输入（目前没用上，留作批量评测的入口）。"""

        return [await self.ainvoke(item) for item in inputs]
