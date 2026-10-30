"""四个 Agent 的装配（对应 week11 版本的 agents/ 目录）。

和 openai-agents 版本的关键差别：

* openai-agents 在 **import 时** 就构造 Agent 对象；LangChain 的 ChatOpenAI 在
  没有 API Key 时会直接抛错，这会让「只想跑单元测试 / 看 schema」的人也失败。
* 所以这里用 ``lru_cache`` 做成**懒加载单例**：第一次真正调用时才建链，
  同时保证一个进程里只建一次（等价于原版的模块级定义）。
"""

from __future__ import annotations

from functools import lru_cache

from .config import settings
from .llm import StructuredAgent
from .models import FinalAnswer, SQLDraft, TableSelection
from .prompts import (
    RESULT_SUMMARY_PROMPT,
    SQL_GENERATE_PROMPT,
    SQL_REWRITE_PROMPT,
    TABLE_SELECT_PROMPT,
)


@lru_cache(maxsize=1)
def get_table_selector() -> StructuredAgent:
    """选表：temperature=0，只要分类结果。"""

    return StructuredAgent(
        name="TableSelectAgent",
        system_prompt=TABLE_SELECT_PROMPT,
        output_schema=TableSelection,
        model=settings.primary_model,
        temperature=0.0,
    )


@lru_cache(maxsize=1)
def get_sql_generator() -> StructuredAgent:
    """生成 SQL：temperature=0，避免同题不同 SQL。"""

    return StructuredAgent(
        name="SQLGeneratorAgent",
        system_prompt=SQL_GENERATE_PROMPT,
        output_schema=SQLDraft,
        model=settings.primary_model,
        temperature=0.0,
    )


@lru_cache(maxsize=1)
def get_sql_rewriter() -> StructuredAgent:
    """改写 SQL：留一点温度，避免反复给出同一条错误 SQL。"""

    return StructuredAgent(
        name="SQLRewriteAgent",
        system_prompt=SQL_REWRITE_PROMPT,
        output_schema=SQLDraft,
        model=settings.primary_model,
        temperature=0.2,
    )


@lru_cache(maxsize=1)
def get_result_summarizer() -> StructuredAgent:
    """结果汇总：用更便宜的模型，允许一点措辞自由度。"""

    return StructuredAgent(
        name="ResultSummaryAgent",
        system_prompt=RESULT_SUMMARY_PROMPT,
        output_schema=FinalAnswer,
        model=settings.summary_model,
        temperature=0.3,
    )


def reset_agents() -> None:
    """改过环境变量后重建（测试与 notebook 里用）。"""

    for factory in (
        get_table_selector,
        get_sql_generator,
        get_sql_rewriter,
        get_result_summarizer,
    ):
        factory.cache_clear()
