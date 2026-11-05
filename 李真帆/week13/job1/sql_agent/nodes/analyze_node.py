"""解读节点：把查询结果翻译成业务能直接用的结论（LLM）。"""

from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables.config import RunnableConfig

from ..prompts.templates import ANALYST_HUMAN, ANALYST_SYSTEM
from ..state import GraphState
from ..utils.parsing import oneline
from ..utils.trace import STATUS_OK, get_trace


def make_analyze_node(model: BaseChatModel) -> Callable[[GraphState, RunnableConfig], dict[str, Any]]:
    """构造解读节点。"""
    chain = (
        ChatPromptTemplate.from_messages([
            ("system", ANALYST_SYSTEM),
            ("human", ANALYST_HUMAN),
        ])
        | model
        | StrOutputParser()
    )

    def analyze_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        trace = get_trace(config)
        with trace.span("AnalystAgent", "解读结果") as box:
            answer = chain.invoke({
                "question": state["question"],
                "sql": state["sql"],
                "result": state["result"],
            }).strip()
            box["status"] = STATUS_OK
            box["detail"] = oneline(answer, 60)
        return {"answer": answer, "rejected": False}

    return analyze_node
