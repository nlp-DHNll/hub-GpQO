"""数据库解析、校验与执行（确定性组件）。"""

from .catalog import ForeignKey, SchemaCatalog, get_catalog, make_readonly_url
from .executor import SQLExecutionError, SQLExecutor
from .validator import SQLValidator, normalize_sql

__all__ = [
    "ForeignKey",
    "SQLExecutionError",
    "SQLExecutor",
    "SQLValidator",
    "SchemaCatalog",
    "get_catalog",
    "make_readonly_url",
    "normalize_sql",
]
