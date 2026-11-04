"""agents/ — 四个模块级 StructuredAgent 实例。"""

from .table_selector import table_select_agent
from .sql_generator import sql_generate_agent
from .sql_rewriter import sql_rewrite_agent
from .result_summarizer import result_summary_agent


class Agents:
    """Agent 集合，作为命名空间注入 graph。"""

    def __init__(self):
        self.table_selector = table_select_agent
        self.sql_generator = sql_generate_agent
        self.sql_rewriter = sql_rewrite_agent
        self.summarizer = result_summary_agent


__all__ = [
    "Agents",
    "table_select_agent",
    "sql_generate_agent",
    "sql_rewrite_agent",
    "result_summary_agent",
]
