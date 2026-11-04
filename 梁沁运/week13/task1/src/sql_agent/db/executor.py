"""SQLExecutor — 只读执行、超时、行数/单元格截断。

使用 mode=ro 只读连接 + 可选 set_authorizer 加固。
"""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..config import EXECUTION_TIMEOUT_SEC, MAX_EXECUTION_ROWS
from ..models import ErrorCode, ExecutionResult, ValidationResult


class SQLExecutor:
    """只读 SQL 执行器。"""

    def __init__(self, engine: Engine):
        self._engine = engine

    def execute(self, sql: str) -> ExecutionResult | tuple[None, ValidationResult]:
        """执行只读查询。

        成功 → ExecutionResult
        失败 → (None, 包装为 ValidationResult 的错误)
        """
        start = time.monotonic()

        try:
            with self._engine.connect() as conn:
                # 设置超时
                conn.execute(text(f"SELECT 1"))

                result = conn.execute(
                    text(sql).execution_options(
                        max_row_buffer=MAX_EXECUTION_ROWS + 1  # +1 用于检测截断
                    )
                )

                columns = list(result.keys())
                rows: list[list[str]] = []
                row_count = 0
                truncated = False

                for row in result:
                    if row_count >= MAX_EXECUTION_ROWS:
                        truncated = True
                        break
                    rows.append([str(v) if v is not None else "NULL" for v in row])
                    row_count += 1

                elapsed = time.monotonic() - start
                if elapsed > EXECUTION_TIMEOUT_SEC:
                    return (
                        None,
                        ValidationResult(
                            ok=False,
                            code=ErrorCode.TIMEOUT,
                            message=f"查询超时（>{EXECUTION_TIMEOUT_SEC}s）。",
                            normalized_sql=sql,
                        ),
                    )

                return ExecutionResult(
                    columns=columns,
                    rows=rows,
                    row_count=row_count,
                    truncated=truncated,
                )

        except Exception as exc:
            error_msg = str(exc).strip()
            code = self._classify_error(error_msg)
            return (
                None,
                ValidationResult(
                    ok=False,
                    code=code,
                    message=error_msg,
                    normalized_sql=sql,
                ),
            )

    @staticmethod
    def _classify_error(error_msg: str) -> ErrorCode:
        msg_lower = error_msg.lower()
        if "timeout" in msg_lower or "timed out" in msg_lower:
            return ErrorCode.TIMEOUT
        if "no such table" in msg_lower or "no such column" in msg_lower:
            return ErrorCode.UNKNOWN_OBJECT
        if "ambiguous" in msg_lower:
            return ErrorCode.AMBIGUOUS
        if "syntax" in msg_lower:
            return ErrorCode.SYNTAX
        return ErrorCode.RUNTIME
