# -*- coding: utf-8 -*-
"""多 agent 包：只含「角色」agent，不含编排逻辑。

- base      基类（LLM 调用 + JSON 解析）
- keyword   生成搜索关键词
- summary   对搜索结果做总结
- judge     判断是否补检 + 生成新关键词
- report    生成结构化报告 + HTML

编排（研究引擎）见 backend/engine.py 的 DeepResearch。
"""
from .base import BaseAgent
from .judge import JudgeAgent
from .keyword import KeywordAgent
from .report import ReportAgent
from .summary import SummaryAgent

__all__ = ["BaseAgent", "KeywordAgent", "SummaryAgent", "JudgeAgent", "ReportAgent"]
