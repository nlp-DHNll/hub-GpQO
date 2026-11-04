"""execute 节点（确定性）。

失败时显式 execution=None，同时返回包装为 ValidationResult 的错误。
"""

from __future__ import annotations

from ..db.catalog import SchemaCatalog
from ..db.executor import SQLExecutor
from ..state import SQLAgentState


async def execute_node(
    state: SQLAgentState,
    *,
    catalog: SchemaCatalog,
) -> dict:
    """只读执行。成功返回 ExecutionResult，失败返回 execution=None + validation。"""
    sql = state.get("sql")
    if not sql:
        return {
            "execution": None,
            "last_error": "没有可执行的 SQL",
            "stage": "execute",
        }

    engine = catalog.engine
    executor = SQLExecutor(engine)
    result = executor.execute(sql)

    if isinstance(result, tuple):
        # 失败：(None, ValidationResult)
        _, validation = result
        return {
            "execution": None,
            "validation": validation,
            "last_error": f"执行错误 [{validation.code}]: {validation.message}" if validation else "未知执行错误",
            "stage": "execute",
        }

    # 成功：ExecutionResult
    return {
        "execution": result,
        "stage": "execute",
    }
