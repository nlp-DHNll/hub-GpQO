"""四个 LLM Agent 的模块级 chain 定义。

与 openai-agents 版的对应关系：
- `Agent(instructions=..., output_type=X)` → `ChatPromptTemplate + ChatOpenAI
  .with_structured_output(X)`（LCEL chain，模块级定义、不在每次请求时新建）；
- `Runner.run(agent, prompt)` → `chain.ainvoke({"prompt": prompt})`。
DashScope / DeepSeek 等兼容端点不支持 OpenAI Responses API，结构化输出
统一走 function calling。
"""

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
