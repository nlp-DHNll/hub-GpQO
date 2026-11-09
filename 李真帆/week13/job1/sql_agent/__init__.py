"""SQL 检索智能体（LangGraph 版）。

对外只需要三件事：
    run_agent(question, api_key=...)  —— 跑完整工作流拿结果；
    build_graph(api_key=...)          —— 拿到编译好的状态图；
    REFUSAL_ANSWER                    —— 拒绝话术常量（前端 / 后端共用同一句文案）。
"""

from .config import DB_PATH, DEEPSEEK_API_KEY, REFUSAL_ANSWER
from .graph import build_graph, run_agent

__all__ = ["build_graph", "run_agent", "DB_PATH", "REFUSAL_ANSWER"]


def is_key_configured() -> bool:
    """API Key 是否已配置（非空且不是占位符）。"""
    key = (DEEPSEEK_API_KEY or "").strip()
    return bool(key) and key != "your_api_key"


def describe_database(db_path: str = DB_PATH) -> str:
    """把所有表压缩成一段简介文本（未配置 Key 时的降级展示）。"""
    from .db.parser import DBParser

    parser = DBParser(db_path)
    try:
        return "\n".join(
            f"- {table}（{parser.row_count(table)} 行）字段："
            f"{', '.join(parser.get_table_fields(table))}"
            for table in parser.table_names
        )
    finally:
        parser.close()
