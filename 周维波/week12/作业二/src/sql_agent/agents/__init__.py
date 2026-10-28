"""四个 LangChain 链（等价于 openai-agents 版的模块级 Agent）。

与 openai-agents 版的对应关系：
- Agent(model=..., output_type=...)  ->  build_*_chain()：ChatPromptTemplate
  | ChatOpenAI.with_structured_output(schema, method="function_calling")。
- Runner.run(agent, prompt)          ->  chain.ainvoke({"input": prompt})。
- 模块级 Agent 定义/复用             ->  get_*_chain() 进程级单例，懒加载。

懒加载原因：ChatOpenAI 构造时就需要 API Key（langchain-openai 1.x 会抛错），
懒加载保证无 Key 时导入包、运行测试都不受影响；Key 只在实际调用链时才校验。
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
