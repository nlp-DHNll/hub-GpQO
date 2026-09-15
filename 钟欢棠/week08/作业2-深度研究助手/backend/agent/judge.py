# -*- coding: utf-8 -*-
"""judge —— 判断是否需要补检并生成新关键词的 agent（「判断补检」环）。"""
from __future__ import annotations

import json
import logging

from .. import config
from ..models import JudgeDecision, Source
from .base import BaseAgent

logger = logging.getLogger(__name__)


class JudgeAgent(BaseAgent):
    """判断信息是否足够，不足则给出补充检索的新关键词。"""

    agent_name = "JudgeAgent"
    template_name = "judge_agent.jinja2"

    async def judge(
        self,
        topic: str,
        draft_text: str,
        sources: list[Source],
        searched_keywords: list[str],
    ) -> JudgeDecision:
        logger.info(
            "判断补检：已检关键词 %d 个、累积正文 %d 字、来源 %d 个",
            len(searched_keywords),
            len(draft_text),
            len(sources),
        )
        user_input = json.dumps(
            {
                "searched_keywords": searched_keywords,
                "draft": draft_text,
                "source_count": len(sources),
            },
            ensure_ascii=False,
        )
        decision = await self.call_json(
            {"topic": topic, "today": config.today_str()},
            user_input,
            JudgeDecision,
        )
        logger.info(
            "判断结果: sufficient=%s new_keywords=%s（%s）",
            decision.sufficient,
            decision.new_keywords,
            decision.reason,
        )
        return decision


if __name__ == "__main__":
    # 测试 demo：用模拟发现真实调用 LLM 判断（需要 .env 密钥）
    import asyncio
    import logging

    logging.basicConfig(level=logging.INFO)

    _MOCK_DRAFT = (
        "OpenAI Agents SDK 与 LangGraph 是目前主流的两大 agent 框架。"
        "前者轻量、官方维护，后者把 agent 建模为有向图、适合复杂工作流。"
    )
    _MOCK_SOURCES = [
        Source(url="https://openai.github.io/openai-agents-python/", title="OpenAI Agents SDK 文档"),
        Source(url="https://langchain-ai.github.io/langgraph/", title="LangGraph 文档"),
    ]

    async def _demo() -> None:
        agent = JudgeAgent()
        decision = await agent.judge(
            "2026 年主流 Agent 框架对比",
            _MOCK_DRAFT,
            _MOCK_SOURCES,
            ["Agent 框架", "LangGraph"],
        )
        print("decision:", decision.model_dump())

    asyncio.run(_demo())
