"""修复节点：把错误信息（校验失败 / 数据库报错）回灌后改写出新 SQL（LLM）。

每次进入该节点都会给 repairs 累加器 +1（LangGraph 自动合并），
配合“每轮最多 1 次原地修复”的路由规则使用。
"""

from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables.config import RunnableConfig

from ..prompts.templates import SQL_REPAIR_HUMAN, SQL_REPAIR_SYSTEM
from ..state import GraphState
from ..utils.parsing import oneline, parse_json, pick_sql
from ..utils.trace import STATUS_OK, STATUS_WARN, get_trace


def make_repair_node(model: BaseChatModel) -> Callable[[GraphState, RunnableConfig], dict[str, Any]]:
    """构造修复节点。"""
    chain = (
        ChatPromptTemplate.from_messages([
            ("system", SQL_REPAIR_SYSTEM),
            ("human", SQL_REPAIR_HUMAN),
        ])
        | model
        | StrOutputParser()
    )

    def repair_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        trace = get_trace(config)
        old_sql = state["sql"]
        prev_tried = list(state.get("tried_sql") or [])

        # 错误来源按“谁拦下的”来取：守卫拦的就给语法/只读原因，
        # 审查或执行拦的就给语义原因，避免把上一轮的旧问题喂给模型
        if not state.get("guard_ok", True):
            error = state.get("guard_msg") or "未通过只读校验"
        else:
            error = state.get("critic_issues") or state.get("exec_error") or "未知问题"

        with trace.span("SqlRepairAgent", "修复 SQL") as box:
            raw = chain.invoke({
                "schema": state["schema"],
                "relations": state["relations"],
                "question": state["question"],
                "sql": old_sql,
                "error": error,
            })
            new_sql = pick_sql(parse_json(raw), raw) or old_sql
            if new_sql == old_sql:
                # 修复没产生变化，再校验一次只会得到同样结果，交给下一轮重新生成
                box["status"] = STATUS_WARN
                box["detail"] = "修复未产生变化，转入下一轮重新生成"
            else:
                box["status"] = STATUS_OK
                box["detail"] = oneline(new_sql)

        if new_sql != old_sql and new_sql not in prev_tried:
            prev_tried.append(new_sql)

        return {
            "repairs": 1,  # 累加器：每进一次 repair 计一次修复
            "sql": new_sql,
            "repaired": new_sql != old_sql,
            "tried_sql": prev_tried,
        }

    return repair_node
