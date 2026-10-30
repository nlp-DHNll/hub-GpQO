"""工具层：把数据库能力包装成 LangChain 工具（@tool）。

Agent 不再直接摸 sqlite3，只通过这些工具（或工具背后的同一套方法）看库和跑 SQL，
这样“Agent 能用什么”是显式可数的，也方便后续换库、加缓存或换存储引擎。
"""

from typing import Any

from langchain_core.tools import BaseTool
from langchain.tools import tool

from .config import MAX_RESULT_ROWS
from .db import DBParser, short


def to_markdown(cols: list[str], rows: list[list[Any]], limit: int = MAX_RESULT_ROWS) -> str:
    """把查询结果渲染为简单表格文本（不依赖 tabulate）。"""
    show = rows[:limit]
    lines = [" | ".join(cols)]
    lines.extend(" | ".join(short(v, 40) for v in r) for r in show)
    if len(rows) > limit:
        lines.append(f"...（结果超过 {limit} 行，此处仅展示前 {limit} 行）")
    return "\n".join(lines)


class SqlToolkit:
    """围绕一个 DBParser 构建的工具集。

    - ``tools``：LangChain 工具对象列表，可直接交给带工具能力的模型 / Agent；
    - ``invoke``：按名字调用工具并拿回文本结果，供确定性流程使用。
    """

    def __init__(self, parser: DBParser) -> None:
        self.parser = parser
        self.tools: list[BaseTool] = self._build_tools()
        self._by_name = {t.name: t for t in self.tools}

    # -------------------- 工具定义 --------------------

    def _build_tools(self) -> list[BaseTool]:
        parser = self.parser

        @tool
        def list_tables() -> str:
            """列出数据库中所有业务表、行数和字段名。"""
            return parser.describe_all_tables()

        @tool
        def describe_table(table: str) -> str:
            """查看单张表的完整结构：字段类型、主键、唯一值数量、空值数、取值样例。"""
            if table not in parser.table_names:
                return f"表不存在：{table}，可选表：{', '.join(parser.table_names)}"
            return parser.describe_table(table)

        @tool
        def sample_rows(table: str, limit: int = 3) -> str:
            """抽样查看某张表的真实数据行，用于确认字段里存的内容形态。"""
            if table not in parser.table_names:
                return f"表不存在：{table}"
            cols, rows = parser.get_table_sample(table)
            if not rows:
                return f"{table} 没有数据"
            return to_markdown(cols, rows, max(1, min(limit, 10)))

        @tool
        def check_sql(sql: str) -> str:
            """校验一条 SQL：检查是否为单条只读查询，并用 EXPLAIN 试跑验证语法与字段。"""
            ok, msg = parser.check_sql(sql)
            return "通过" if ok else f"未通过：{msg}"

        @tool
        def execute_sql(sql: str) -> str:
            """执行一条只读 SQL 并返回结果表格（最多展示前若干行）。"""
            ok, msg, cols, rows = parser.execute_sql(sql)
            if not ok:
                return f"执行失败：{msg}"
            return to_markdown(cols, rows) if cols else "（无结果集）"

        return [list_tables, describe_table, sample_rows, check_sql, execute_sql]

    # -------------------- 调用入口 --------------------

    def call(self, name: str, **kwargs: Any) -> str:
        """按名字调用工具，返回文本结果。

        对未知工具名与工具内部异常都做兜底，避免一次工具故障打断整条链。
        """
        target = self._by_name.get(name)
        if target is None:
            return f"未知工具：{name}，可用工具：{', '.join(self._by_name)}"
        try:
            return str(target.invoke(kwargs))
        except Exception as exc:  # 工具异常统一转成文本回灌给 Agent
            return f"工具 {name} 执行异常：{type(exc).__name__}: {exc}"

    def describe(self) -> str:
        """工具清单文本，写进 Agent 提示词，让它明确自己有哪些手段。"""
        return "\n".join(f"- {t.name}：{t.description}" for t in self.tools)
