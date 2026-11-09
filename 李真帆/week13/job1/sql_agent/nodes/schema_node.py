"""选表节点：从全库中挑出回答问题所需的最小表集合，并装配上下文（LLM）。

输入是“表清单 + 工具清单”，输出是 schema 文本与外键关系，
后续 generate / critic / repair 都复用这份上下文。
"""

from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables.config import RunnableConfig

from ..db.parser import DBParser
from ..prompts.templates import SCHEMA_HUMAN, SCHEMA_SYSTEM
from ..state import GraphState
from ..tools.db_toolkit import SqlToolkit
from ..utils.parsing import normalize_tables, oneline, parse_json
from ..utils.trace import STATUS_OK, STATUS_WARN, get_trace


def make_schema_node(model: BaseChatModel, parser: DBParser,
                     toolkit: SqlToolkit) -> Callable[[GraphState, RunnableConfig], dict[str, Any]]:
    """构造选表节点。"""
    chain = (
        ChatPromptTemplate.from_messages([
            ("system", SCHEMA_SYSTEM),
            ("human", SCHEMA_HUMAN),
        ])
        | model
        | StrOutputParser()
    )

    def schema_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        trace = get_trace(config)
        question = state["question"]
        tables: list[str] = []
        reason = ""
        with trace.span("SchemaAgent", "选表") as box:
            raw = chain.invoke({
                "tool_list": toolkit.describe(),
                "all_tables": parser.describe_all_tables(),
                "question": question,
            })
            data = parse_json(raw)
            tables = normalize_tables(data.get("tables"), parser.table_names)
            reason = str(data.get("reason") or "")

            if tables:
                box["status"] = STATUS_OK
                box["detail"] = f"{tables} | {oneline(reason, 50)}"
            else:
                # 兜底：选不出表时退化为前几张表，不让整条链断掉
                tables = parser.table_names[:5]
                box["status"] = STATUS_WARN
                box["detail"] = f"未得到有效表名，回退为 {tables}"

        schema = "\n\n".join(parser.describe_table(t) for t in tables)
        relations = parser.describe_relations(tables)
        return {"tables": tables, "reason": reason,
                "schema": schema, "relations": relations}

    return schema_node
