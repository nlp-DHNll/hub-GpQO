"""ResultSummaryAgent — 把结构化结果转成忠实、可读的中文答案。

工具：无。
输出：FinalAnswer。
"""

from __future__ import annotations

from ..llm import StructuredAgent
from ..models import FinalAnswer

RESULT_SUMMARY_PROMPT = """你是数据分析助手。只依据给定的 SQL 查询结果回答用户问题。

规则：
1. 数字必须与结果一致，不得编造或外推；
2. 结果是多行时，给出整体结论并列举关键数据；
3. 结果为空时，明确回答"未查询到符合条件的数据"，不要猜测原因；
4. 结果被截断时，在 caveats 中说明只展示了部分数据；
5. 不要修改 SQL，不要声称执行了未提供的查询；
6. evidence 中列出支撑结论的具体数值。"""

result_summary_agent = StructuredAgent(
    name="ResultSummaryAgent",
    output_schema=FinalAnswer,
    system_prompt=RESULT_SUMMARY_PROMPT,
    temperature=0.3,
)

__all__ = ["result_summary_agent", "RESULT_SUMMARY_PROMPT"]
