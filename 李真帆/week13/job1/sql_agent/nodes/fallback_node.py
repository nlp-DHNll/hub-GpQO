"""兜底节点：重试预算耗尽时的失败说明（确定性，不调用 LLM）。"""

from typing import Any, Callable

from langchain_core.runnables.config import RunnableConfig

from ..state import GraphState
from ..utils.parsing import oneline
from ..utils.trace import STATUS_FAIL, get_trace


def make_fallback_node() -> Callable[[GraphState, RunnableConfig], dict[str, Any]]:
    """构造兜底节点。

    走到这里说明：生成/校验/执行在 MAX_ROUNDS 轮内都没能成功，
    给出明确的失败说明，而不是静默返回空。
    """

    def fallback_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        get_trace(config).record(
            "Fallback", "输出兜底",
            detail="重试预算耗尽，直接说明失败原因", status=STATUS_FAIL,
        )
        answer = (f"很抱歉，未能成功执行查询（最后尝试的 SQL："
                  f"{oneline(state.get('sql') or '', 200) or '无'}）。")
        return {"answer": answer, "rejected": False}

    return fallback_node
