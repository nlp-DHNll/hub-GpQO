"""只读守卫节点：静态校验 + EXPLAIN 试跑（确定性，不调用 LLM）。

能不能执行必须由确定性规则说了算，这一步刻意不用 LLM。
"""

from typing import Any, Callable

from langchain_core.runnables.config import RunnableConfig

from ..db.parser import DBParser
from ..state import GraphState
from ..utils.parsing import oneline
from ..utils.trace import STATUS_FAIL, STATUS_OK, get_trace


def make_guard_node(parser: DBParser) -> Callable[[GraphState, RunnableConfig], dict[str, Any]]:
    """构造只读守卫节点。"""

    def guard_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        trace = get_trace(config)
        sql = state.get("sql") or ""
        ok, msg = parser.check_sql(sql) if sql else (False, "SQL 为空")
        with trace.span("SqlGuard", "只读守卫") as box:
            box["status"] = STATUS_OK if ok else STATUS_FAIL
            box["detail"] = "通过" if ok else oneline(msg)
        return {"guard_ok": ok, "guard_msg": msg}

    return guard_node
