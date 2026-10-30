"""四个 LLM 调用链的模块级定义（LangChain LCEL，导入时构建一次）。

每个 Agent 都是 `ChatPromptTemplate | ChatOpenAI.with_structured_output(...)`，
输入 `{"prompt": <本次提示词>}`，输出对应的 Pydantic 契约。
LangSmith 追踪默认关闭，除非设置 LANGSMITH_TRACING/LANGSMITH_API_KEY。
"""

from __future__ import annotations

from .result_summarizer import result_summary_chain
from .sql_generator import sql_generator_chain
from .sql_rewriter import sql_rewriter_chain
from .table_selector import table_selector_chain

__all__ = [
    "result_summary_chain",
    "sql_generator_chain",
    "sql_rewriter_chain",
    "table_selector_chain",
]
