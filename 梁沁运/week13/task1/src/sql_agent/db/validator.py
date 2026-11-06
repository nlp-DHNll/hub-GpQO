"""SQLValidator — 安全门禁 + EXPLAIN 编译校验。

多层防御：
1. 只接受单条 SELECT / WITH ... SELECT
2. 拒绝危险关键字（INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/PRAGMA/ATTACH）
3. 拒绝多语句（分号分隔）
4. EXPLAIN dry-run 编译校验（不真执行）

不实现 check_sql（notebook 版的 engine.begin() 真执行并提交，不得复用）。
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..models import ErrorCode, ValidationResult

# 危险关键字
DANGEROUS_KEYWORDS = re.compile(
    r'\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|PRAGMA|ATTACH|DETACH|REINDEX|REPLACE)\b',
    re.IGNORECASE,
)

# SELECT 白名单
SELECT_PATTERN = re.compile(
    r'^\s*(SELECT|WITH)\b',
    re.IGNORECASE | re.DOTALL,
)


class SQLValidator:
    """SQL 安全校验器。"""

    def __init__(self, engine: Engine):
        self._engine = engine

    def validate(self, sql: str) -> ValidationResult:
        """执行全部安全检查 + EXPLAIN 编译校验。"""
        raw = sql.strip()

        # 去尾分号
        if raw.endswith(";"):
            raw = raw[:-1].strip()

        # 1. 空语句
        if not raw:
            return ValidationResult(
                ok=False,
                code=ErrorCode.SYNTAX,
                message="SQL 语句为空。",
            )

        # 2. 多语句检查（分号分隔）
        # 去除字符串字面量中的分号干扰后检查
        cleaned = self._strip_string_literals(raw)
        if ";" in cleaned:
            return ValidationResult(
                ok=False,
                code=ErrorCode.UNSAFE,
                message="检测到多语句（分号分隔）。仅允许单条 SQL。",
            )

        # 3. SELECT / WITH 白名单
        if not SELECT_PATTERN.match(raw):
            return ValidationResult(
                ok=False,
                code=ErrorCode.UNSAFE,
                message="仅允许 SELECT 或 WITH ... SELECT 语句。",
                normalized_sql=raw,
            )

        # 4. 危险关键字
        match = DANGEROUS_KEYWORDS.search(raw)
        if match:
            return ValidationResult(
                ok=False,
                code=ErrorCode.UNSAFE,
                message=f"检测到危险关键字: {match.group(0)}。仅允许只读查询。",
                normalized_sql=raw,
            )

        # 5. EXPLAIN 编译校验（dry-run）
        try:
            with self._engine.connect() as conn:
                conn.execute(text(f"EXPLAIN {raw}"))
        except Exception as exc:
            error_msg = str(exc).strip()
            # 分类错误码
            code = self._classify_error(error_msg, raw)
            return ValidationResult(
                ok=False,
                code=code,
                message=error_msg,
                normalized_sql=raw,
            )

        return ValidationResult(
            ok=True,
            normalized_sql=raw,
        )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _strip_string_literals(self, sql: str) -> str:
        """移除字符串字面量内容，避免干扰分号检测。"""
        # 替换单引号内的内容
        result = re.sub(r"'[^']*'", "''", sql)
        # 替换双引号内的内容
        result = re.sub(r'"[^"]*"', '""', result)
        return result

    def _classify_error(self, error_msg: str, _sql: str) -> ErrorCode:
        """根据错误信息映射 ErrorCode。"""
        msg_lower = error_msg.lower()

        if "no such table" in msg_lower or "no such column" in msg_lower:
            return ErrorCode.UNKNOWN_OBJECT
        if "ambiguous" in msg_lower:
            return ErrorCode.AMBIGUOUS
        if "syntax" in msg_lower or "near" in msg_lower:
            return ErrorCode.SYNTAX
        return ErrorCode.RUNTIME
