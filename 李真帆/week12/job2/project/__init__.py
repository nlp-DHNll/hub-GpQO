"""week12 job2：基于 LangChain(LCEL) 的多 Agent 数据库查询项目。

模块划分：
    config.py    —— 模型、数据库路径与流程常量
    db.py        —— 原生 sqlite3 的解析 / 校验 / 执行（不依赖 LLM）
    tools.py     —— 把数据库能力包装成 LangChain 工具（@tool）
    prompts.py   —— 各 Agent 的提示词模板
    parsing.py   —— LLM 输出的容错解析（JSON / SQL / 布尔 / 表名归一化）
    trace.py     —— Agent 执行轨迹记录
    agents.py    —— 5 个专职 Agent 的 LCEL 实现
    pipeline.py  —— 用 LCEL 串联各 Agent，并控制重试轮次

外部只需要::

    from project import run_query
    result = run_query("每种音乐类型下有多少首曲目？")
"""

from .config import DB_PATH, DEEPSEEK_API_KEY, DEEPSEEK_MODEL
from .db import DBParser
from .pipeline import SqlAgentPipeline, run_query
from .trace import Trace

__all__ = [
    "DB_PATH",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "DBParser",
    "SqlAgentPipeline",
    "Trace",
    "run_query",
    "is_key_configured",
    "describe_database",
]


def is_key_configured() -> bool:
    """判断是否已经填好 DeepSeek API Key。"""
    key = (DEEPSEEK_API_KEY or "").strip()
    return bool(key) and key != "your_api_key"


def describe_database(db_path: str = DB_PATH) -> str:
    """打印用的数据库概览（不调用大模型）。

    流程：读表清单 -> 逐表取字段 -> 拼成文本，同时附上全库外键关系。
    """
    parser = DBParser(db_path)
    try:
        lines = [f"数据库：{db_path}",
                 f"业务表数量：{len(parser.table_names)}",
                 "",
                 "表清单：",
                 parser.describe_all_tables(),
                 "",
                 "外键关系：",
                 parser.describe_relations()]
        return "\n".join(lines)
    finally:
        parser.close()
