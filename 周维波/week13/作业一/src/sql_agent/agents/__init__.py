"""四个 LangChain 链（LangGraph 节点的 LLM 调用层）。

- 链由 ChatPromptTemplate | ChatOpenAI.with_structured_output(schema) 组成，
  与原 openai-agents 版的 output_type 语义一致（走 function calling）。
- get_*_chain() 进程级单例、懒加载：无 API Key 时导入包与跑测试都不受影响。
"""

from __future__ import annotations

from .llm import get_chat_model
from .result_summarizer import (
    build_result_summary_chain,
    get_result_summary_chain,
)
from .sql_generator import build_sql_generator_chain, get_sql_generator_chain
from .sql_rewriter import build_sql_rewriter_chain, get_sql_rewriter_chain
from .table_selector import (
    build_table_selector_chain,
    get_table_selector_chain,
)

__all__ = [
    "get_chat_model",
    "build_table_selector_chain",
    "get_table_selector_chain",
    "build_sql_generator_chain",
    "get_sql_generator_chain",
    "build_sql_rewriter_chain",
    "get_sql_rewriter_chain",
    "build_result_summary_chain",
    "get_result_summary_chain",
]
