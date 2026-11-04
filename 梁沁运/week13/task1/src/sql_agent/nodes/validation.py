"""validate_sql 节点（确定性）。"""

from __future__ import annotations

from ..db.catalog import SchemaCatalog
from ..state import SQLAgentState


async def validate_sql_node(
    state: SQLAgentState,
    *,
    catalog: SchemaCatalog,
) -> dict:
    """安全检查 + EXPLAIN 编译校验。不递增计数器。"""
    sql = state.get("sql")
    if not sql:
        return {
            "validation": None,
            "last_error": "没有可校验的 SQL",
            "stage": "validate_sql",
        }

    engine = catalog.engine
    # 延迟导入避免循环
    from ..db.validator import SQLValidator
    validator = SQLValidator(engine)
    result = validator.validate(sql)

    return {
        "validation": result,
        "stage": "validate_sql",
    }
