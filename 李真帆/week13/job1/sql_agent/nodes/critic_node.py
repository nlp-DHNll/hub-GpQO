"""审查节点：只看语义是否正确，不产出改写后的 SQL（LLM）。

与生成节点分离，是为了避免“自己写、自己批”带来的自我肯定偏差。
"""

from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables.config import RunnableConfig

from ..prompts.templates import SQL_CRITIC_HUMAN, SQL_CRITIC_SYSTEM
from ..state import GraphState
from ..utils.parsing import as_bool, oneline, parse_json
from ..utils.trace import STATUS_FAIL, STATUS_OK, STATUS_WARN, get_trace


def make_critic_node(model: BaseChatModel) -> Callable[[GraphState, RunnableConfig], dict[str, Any]]:
    """构造语义审查节点。"""
    chain = (
        ChatPromptTemplate.from_messages([
            ("system", SQL_CRITIC_SYSTEM),
            ("human", SQL_CRITIC_HUMAN),
        ])
        | model
        | StrOutputParser()
    )

    def critic_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        trace = get_trace(config)
        ok, issues = True, ""
        with trace.span("SqlCriticAgent", "语义审查") as box:
            raw = chain.invoke({
                "schema": state["schema"],
                "relations": state["relations"],
                "question": state["question"],
                "sql": state["sql"],
            })
            data = parse_json(raw)
            if not data:
                # 审查结果不可解析时默认放行，避免流程死循环，但明确标注
                box["status"] = STATUS_WARN
                box["detail"] = "审查结果不可解析，默认放行"
            else:
                ok = as_bool(data.get("valid"), default=True)
                issues = str(data.get("issues") or "")
                if ok:
                    box["status"] = STATUS_OK
                    box["detail"] = "语义通过"
                else:
                    box["status"] = STATUS_FAIL
                    box["detail"] = oneline(issues)
        return {"critic_ok": ok, "critic_issues": issues}

    return critic_node
