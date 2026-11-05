"""拒绝节点：不相关问题直接输出固定话术（确定性，不调用 LLM）。"""

from typing import Any, Callable

from langchain_core.runnables.config import RunnableConfig

from ..config import REFUSAL_ANSWER
from ..state import GraphState
from ..utils.trace import STATUS_FAIL, get_trace


def make_refuse_node() -> Callable[[GraphState, RunnableConfig], dict[str, Any]]:
    """构造拒绝节点。

    话术来自 config.REFUSAL_ANSWER 常量，不经过 LLM，
    保证前端 / CLI / 后端任何入口拿到的文案永远一致。
    """

    def refuse_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        get_trace(config).record(
            "Refuse", "业务拦截",
            detail="不相关问题，拒绝回答", status=STATUS_FAIL,
        )
        return {"answer": REFUSAL_ANSWER, "rejected": True}

    return refuse_node
