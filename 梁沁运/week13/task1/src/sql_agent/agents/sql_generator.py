"""SQLGeneratorAgent — 基于问题 + 已选表详细 schema 生成 SQLite SELECT。

工具：无。cannot_fix 恒为 False。
输出：SQLDraft。
"""

from __future__ import annotations

from ..llm import StructuredAgent
from ..models import SQLDraft

SQL_GENERATOR_PROMPT = """你是 SQLite SQL 专家。只使用给定的表、列和连接关系生成 SQL。

规则：
1. 只生成一条 SELECT 或 WITH ... SELECT 语句；
2. 禁止 INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/PRAGMA/ATTACH；
3. 表名、列名必须与 schema 完全一致（Chinook 列名为 PascalCase）；
4. 多表查询使用显式 JOIN，不依赖隐式笛卡尔积；
5. 需要排序的结果给出确定性 ORDER BY；
6. 明细查询默认 LIMIT 200；聚合查询不加 LIMIT；
7. 日期使用 SQLite 语法（如 strftime），不要使用 MySQL 函数；
8. 输出 sql、explanation、assumptions。"""

sql_generate_agent = StructuredAgent(
    name="SQLGeneratorAgent",
    output_schema=SQLDraft,
    system_prompt=SQL_GENERATOR_PROMPT,
    temperature=0.0,
)

__all__ = ["sql_generate_agent", "SQL_GENERATOR_PROMPT"]
