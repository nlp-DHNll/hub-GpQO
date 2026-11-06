"""SQLRewriteAgent — 根据精确错误修复 SQL，不重新回答整个问题。

工具：无。防止模型通过工具反复试错绕过预算。
输出：SQLDraft，cannot_fix=True 时 sql 为空。
"""

from __future__ import annotations

from ..llm import StructuredAgent
from ..models import SQLDraft

SQL_REWRITER_PROMPT = """你是 SQLite SQL 修复专家。只修复给定 SQL 中导致错误的部分，保持用户原始查询意图不变。

规则：
1. 根据错误码定位问题：unsafe / syntax / unknown_object / ambiguous / runtime / timeout；
2. 只使用给定 schema 中的表和列；
3. 不要通过改变业务含义来"绕过"错误；
4. 不要重复已失败的 SQL；
5. 如果问题本身无法用当前数据库回答，返回 cannot_fix=true 并说明原因。"""

sql_rewrite_agent = StructuredAgent(
    name="SQLRewriteAgent",
    output_schema=SQLDraft,
    system_prompt=SQL_REWRITER_PROMPT,
    temperature=0.2,
)

__all__ = ["sql_rewrite_agent", "SQL_REWRITER_PROMPT"]
