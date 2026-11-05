"""生成节点：基于 schema 与外键，把问题翻译成一条只读查询（LLM）。

每次进入该节点都会给 rounds 累加器 +1（LangGraph 自动合并），
并做空 SQL / 重复 SQL 去重：无效时置 ``skipped``，由路由决定重新生成或放弃。
"""

from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables.config import RunnableConfig

from ..prompts.templates import SQL_GEN_HUMAN, SQL_GEN_SYSTEM
from ..state import GraphState
from ..utils.parsing import oneline, parse_json, pick_sql
from ..utils.trace import STATUS_FAIL, STATUS_OK, STATUS_WARN, get_trace


def make_generate_node(model: BaseChatModel) -> Callable[[GraphState, RunnableConfig], dict[str, Any]]:
    """构造生成节点。"""
    chain = (
        ChatPromptTemplate.from_messages([
            ("system", SQL_GEN_SYSTEM),
            ("human", SQL_GEN_HUMAN),
        ])
        | model
        | StrOutputParser()
    )

    def generate_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        trace = get_trace(config)
        prev_tried = list(state.get("tried_sql") or [])
        with trace.span("SqlGeneratorAgent", "生成 SQL") as box:
            raw = chain.invoke({
                "schema": state["schema"],
                "relations": state["relations"],
                "question": state["question"],
            })
            sql = pick_sql(parse_json(raw), raw)
            is_new = bool(sql) and sql not in prev_tried
            if not sql:
                box["status"] = STATUS_FAIL
                box["detail"] = "模型未返回有效 SQL"
            elif not is_new:
                box["status"] = STATUS_WARN
                box["detail"] = "与已尝试过的 SQL 重复"
            else:
                prev_tried.append(sql)
                box["status"] = STATUS_OK
                box["detail"] = oneline(sql)

        return {
            "rounds": 1,  # 累加器：每进一次 generate 计一轮
            "sql": sql,
            "gen_sql": sql,
            "repaired": False,
            "skipped": not is_new,
            "tried_sql": prev_tried,
        }

    return generate_node
