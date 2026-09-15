# -*- coding: utf-8 -*-
"""所有角色 agent 的基类。

以 base model（默认 deepseek-v4-flash，.env 的 MODEL_NAME 可覆盖）为基础发起
一次「无工具」的 LLM 调用。子类通过 agent_name / template_name 指定角色名与
提示词模板；本类负责：渲染提示词（Jinja2）、构建无工具 Agent、Runner.run 调用、
并把输出解析成 pydantic 对象。

对齐 openai-agents 约定：chat_completions 接口 + 关闭 tracing。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TypeVar

from agents import Agent, Runner, set_default_openai_api, set_tracing_disabled
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, ValidationError

from .. import config

# SDK 全局初始化（chat_completions 接口 + 关闭 tracing）
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

_env = Environment(loader=FileSystemLoader(str(config.TEMPLATE_DIR)))

# 所有 LLM 调用以此为基础模型
BASE_MODEL = config.MODEL_NAME

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def parse_json(text: str, output_cls: type[T]) -> T:
    """把模型输出解析为 output_cls 实例。

    DeepSeek 不支持 SDK 的 output_type，因此提示词要求模型输出唯一 JSON 并用
    ```json 代码块包裹。这里先尝试解析代码块内容（正常路径一次成功），失败再
    回退到原始输出。全部失败时抛出 ValueError，附诊断信息。
    """
    candidates: list[tuple[str, str]] = []
    fence = _extract_fence(text)
    if fence:
        candidates.append(("```json 代码块", fence))
    candidates.append(("原始输出", text))

    last_err: Exception | None = None
    failures: list[str] = []
    for label, candidate in candidates:
        if not candidate:
            continue
        try:
            return output_cls.model_validate_json(candidate)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            failures.append(_describe_failure(label, exc))

    snippet = (text or "").replace("\n", " ")[:200]
    raise ValueError(
        f"无法把模型输出解析为 {output_cls.__name__}：共尝试 {len(candidates)} 个候选，全部失败。\n"
        f"输出片段（前 200 字符）: {snippet}\n"
        + "\n".join(f"  - {f}" for f in failures)
    ) from last_err


def _describe_failure(label: str, exc: Exception) -> str:
    """把一次候选解析失败格式化成一行诊断信息。"""
    if isinstance(exc, ValidationError):
        errs = exc.errors()
        first = errs[0] if errs else {}
        if first.get("type") == "json_invalid":
            inner = (first.get("ctx") or {}).get("error")
            if isinstance(inner, json.JSONDecodeError):
                return f"[{label}] JSON 语法错误: {inner.msg}（位置 {inner.pos}）"
            return f"[{label}] JSON 语法错误: {first.get('msg')}"
        shown = errs[:3]
        fields = "; ".join(
            f"{'.'.join(str(p) for p in e.get('loc', ())) or '(根)'}: {e.get('msg')}"
            for e in shown
        )
        more = f"（共 {len(errs)} 处）" if len(errs) > 3 else ""
        return f"[{label}] pydantic 校验失败: {fields}{more}"
    if isinstance(exc, json.JSONDecodeError):
        return f"[{label}] JSON 语法错误: {exc.msg}（位置 {exc.pos}）"
    return f"[{label}] {type(exc).__name__}: {exc}"


def _extract_fence(text: str) -> str | None:
    """从 ```json ... ``` 代码块中提取 JSON 文本。"""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    return m.group(1).strip() if m else None


class BaseAgent:
    """角色 agent 基类。子类需定义 agent_name 与 template_name。"""

    agent_name: str = "BaseAgent"
    template_name: str = ""

    def __init__(self, model: str | None = None):
        self.model = model or BASE_MODEL

    def _render(self, template_name: str | None = None, **vars) -> str:
        """渲染系统提示词模板（提示词与代码分离）。"""
        return _env.get_template(template_name or self.template_name).render(**vars)

    async def _run(self, system_vars: dict, user_input: str, template_name: str | None = None) -> str:
        """构建无工具 Agent 发起一次调用，返回模型最终输出文本。

        DeepSeek 偶发返回 200 但 content 为空（与超时无关）。空输出对后续流程无
        意义，因此重试 LLM_RETRIES 次，每次失败退避 1 秒。
        """
        tpl = template_name or self.template_name
        logger.info("[%s] 开始 LLM 调用 model=%s 模板=%s", self.agent_name, self.model, tpl)

        agent = Agent(
            model=self.model,
            name=self.agent_name,
            instructions=self._render(template_name, **system_vars),
        )
        final = ""
        for attempt in range(1, config.LLM_RETRIES + 1):
            result = await Runner.run(agent, user_input, max_turns=1)
            final = (result.final_output or "").strip()
            if final:
                break
            logger.warning(
                "[%s] 第 %d/%d 次调用返回空输出，退避 1s 后重试",
                self.agent_name,
                attempt,
                config.LLM_RETRIES,
            )
            await asyncio.sleep(1.0)
        logger.info("[%s] LLM 调用完成 输出 %d 字符", self.agent_name, len(final))
        return final

    async def call_json(
        self,
        system_vars: dict,
        user_input: str,
        output_cls: type[T],
        template_name: str | None = None,
    ) -> T:
        """调用一次并把输出解析为 output_cls 实例。"""
        text = await self._run(system_vars, user_input, template_name)
        try:
            return parse_json(text, output_cls)
        except Exception:
            logger.exception("解析 %s 的输出为 %s 失败", self.agent_name, output_cls.__name__)
            raise


if __name__ == "__main__":
    # 本地自检：验证 JSON 解析（直接 + fence 兜底）与提示词渲染（不调用 LLM）
    from ..models import JudgeDecision, KeywordOutput

    d1 = parse_json('{"keywords": ["Agent 框架", "对比评测"]}', KeywordOutput)
    print("直接解析 OK:", d1.keywords)

    text = "结果如下：\n```json\n{\"sufficient\": false, \"reason\": \"缺少对比数据\", \"new_keywords\": [\"LangGraph vs OpenAI Agents SDK\"]}\n```"
    d2 = parse_json(text, JudgeDecision)
    print("fence 兜底 OK:", d2.model_dump())

    class _Dummy(BaseAgent):
        agent_name = "Dummy"
        template_name = "keyword_agent.jinja2"

    sys_prompt = _Dummy()._render(topic="测试主题", today="2026-09-10")
    assert "关键词" in sys_prompt
    print("提示词模板渲染 OK")

    try:
        parse_json("这不是 JSON", JudgeDecision)
        print("FAIL: 应当抛错却没抛")
    except ValueError as exc:
        print("失败诊断示例：\n" + str(exc))
    print("base 自检 OK")
