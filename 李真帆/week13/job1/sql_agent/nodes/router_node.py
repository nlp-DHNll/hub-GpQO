"""相关性路由节点：判断问题是否属于音乐数据库业务范围（LLM）。"""

from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables.config import RunnableConfig

from ..prompts.templates import ROUTER_HUMAN, ROUTER_SYSTEM
from ..state import GraphState
from ..utils.parsing import as_bool, oneline, parse_json
from ..utils.trace import STATUS_FAIL, STATUS_OK, get_trace


def make_router_node(model: BaseChatModel) -> Callable[[GraphState, RunnableConfig], dict[str, Any]]:
    """构造相关性路由节点。

    输出 ``relevant`` 与理由；模糊问题默认放行（选表节点本身有兜底），
    只拦截明显无关的问题，避免误杀。
    """
    chain = (
        ChatPromptTemplate.from_messages([
            ("system", ROUTER_SYSTEM),
            ("human", ROUTER_HUMAN),
        ])
        | model
        | StrOutputParser()
    )

    def router_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        trace = get_trace(config)
        question = state["question"]
        with trace.span("Router", "相关性路由") as box:
            raw = chain.invoke({"question": question})
            data = parse_json(raw)
            relevant = as_bool(data.get("relevant"), default=True)
            reason = str(data.get("reason") or "")
            if relevant:
                box["status"] = STATUS_OK
                box["detail"] = oneline(reason, 50) or "属于音乐库业务查询"
            else:
                box["status"] = STATUS_FAIL
                box["detail"] = oneline(reason, 50) or "超出业务范围"
        return {"relevant": relevant, "reason": reason}

    return router_node
