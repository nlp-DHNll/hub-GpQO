"""执行节点：在只读连接上跑 SQL，并把结果渲染成表格文本（确定性）。"""

from typing import Any, Callable

from langchain_core.runnables.config import RunnableConfig

from ..db.parser import DBParser
from ..state import GraphState
from ..tools.db_toolkit import to_markdown
from ..utils.parsing import oneline
from ..utils.trace import STATUS_FAIL, STATUS_OK, get_trace


def make_execute_node(parser: DBParser) -> Callable[[GraphState, RunnableConfig], dict[str, Any]]:
    """构造执行节点。"""

    def execute_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        trace = get_trace(config)
        rows_count = 0
        with trace.span("SqlExecutor", "执行 SQL") as box:
            ok, msg, cols, rows = parser.execute_sql(state["sql"])
            if ok:
                result = to_markdown(cols, rows) if cols else "（无结果集）"
                rows_count = len(rows)
                box["status"] = STATUS_OK
                box["detail"] = f"取回 {rows_count} 行"
            else:
                result = ""
                box["status"] = STATUS_FAIL
                box["detail"] = oneline(msg)
        return {"exec_ok": ok, "exec_error": "" if ok else msg,
                "result": result, "row_count": rows_count}

    return execute_node
