"""TableSelectAgent — 从表清单中选择回答问题所需的最少表集合。

工具：get_table_schema(table)，白名单校验，只允许访问 11 张业务表。
输出：TableSelection。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..db.catalog import BUSINESS_TABLES
from ..llm import StructuredAgent
from ..models import TableSelection


# ------------------------------------------------------------------
# 工具定义
# ------------------------------------------------------------------
class GetTableSchemaInput(BaseModel):
    table: str = Field(description="要查看详细 schema 的表名")


# 工具的实际实现将在节点层通过 catalog 注入
# 这里只定义签名，实际逻辑在 table_select_tools 节点


def _make_get_table_schema_tool(catalog) -> StructuredTool:
    """创建 get_table_schema 工具（需要 catalog 才能创建）。"""

    def _get_table_schema(table: str) -> str:
        """返回单表的详细 schema，包括列、类型、统计、样例、外键。"""
        if table not in BUSINESS_TABLES:
            return f"错误：表 '{table}' 不在数据库中。合法表名: {', '.join(sorted(BUSINESS_TABLES))}"
        return catalog.render_schema([table])

    return StructuredTool.from_function(
        func=_get_table_schema,
        name="get_table_schema",
        description="获取指定表的详细 schema：列名、类型、可空、distinct、min/max/mode、3 行样例、关联外键。",
        args_schema=GetTableSchemaInput,
    )


# ------------------------------------------------------------------
# System prompt
# ------------------------------------------------------------------
TABLE_SELECTOR_PROMPT = """你是 SQLite 数据库分析专家。根据用户问题，从给定表清单中选择回答所需的最少表集合。

规则：
1. 只能从清单中选择表，禁止臆造表名；
2. 多表问题必须返回所有需要的表；
3. 不要生成 SQL，不要猜测连接条件；
4. 如果问题与数据库无关、信息不足或存在歧义，将 needs_clarification 设为 true，并提出一个具体的澄清问题；
5. 只输出结构化结果。"""


# ------------------------------------------------------------------
# 模块级实例
# ------------------------------------------------------------------
def create_table_select_agent(tools: list | None = None) -> StructuredAgent:
    """工厂函数，由节点层注入工具后创建。"""
    return StructuredAgent(
        name="TableSelectAgent",
        output_schema=TableSelection,
        system_prompt=TABLE_SELECTOR_PROMPT,
        temperature=0.0,
        tools=tools or [],
    )


# 默认无工具实例（仅用于测试/导入）
table_select_agent = create_table_select_agent()


__all__ = [
    "create_table_select_agent",
    "table_select_agent",
    "_make_get_table_schema_tool",
    "TABLE_SELECTOR_PROMPT",
    "GetTableSchemaInput",
]
