"""数据库访问层：SQLite 元信息解析 + SQL 只读校验 + 执行。

这一层不依赖任何 Agent / LLM，纯粹是 Python + sqlite3 的能力，
上层的工具（tools.py）与 Agent 都通过它访问数据库。
"""

import re
import sqlite3
from pathlib import Path
from typing import Any

from .config import INTERNAL_TABLES, MAX_CELL_CHARS, MAX_RESULT_ROWS


def quote_identifier(name: str) -> str:
    """把表名/列名包成 SQLite 双引号标识符，并转义内部双引号。

    避免表/列名带空格、关键字或引号时拼出的 SQL 语法错乱。
    """
    return '"' + str(name).replace('"', '""') + '"'


def short(value: Any, limit: int = MAX_CELL_CHARS) -> str:
    """把任意单元格值转为定长文本，防止 BLOB/长文本把 prompt 撑爆。"""
    if value is None:
        return "NULL"
    text = value.decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else str(value)
    text = text.replace("\n", " ").replace("\r", " ")
    return text if len(text) <= limit else text[:limit] + "..."


class DBParser:
    """SQLite 数据库解析器。

    负责读出表 / 字段 / 类型 / 主外键 / 统计特征 / 样例数据，
    并组织成文本供上层 Agent 使用；同时提供 SQL 的静态校验与执行能力。
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

        # 以只读 URI 方式连接，避免 Agent 生成的 SQL 误改数据库
        # （Windows 路径需转正斜杠，否则会被 URI 解析吃掉转义字符）
        try:
            self.conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
            self.readonly = True
        except sqlite3.OperationalError:
            # 兜底：只读模式不可用时（例如文件被占用）退回普通连接
            self.conn = sqlite3.connect(db_path)
            self.readonly = False
        self.conn.row_factory = sqlite3.Row

        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        self.table_names = [r[0] for r in cursor.fetchall() if r[0] not in INTERNAL_TABLES]
        if not self.table_names:
            raise ValueError(f"数据库中没有可用的业务表：{db_path}")

        self._table_fields: dict[str, dict[str, dict[str, Any]]] = {}
        self._table_rows: dict[str, list[sqlite3.Row]] = {}
        self._row_counts: dict[str, int] = {}
        self.foreign_keys: list[dict[str, Any]] = []

        for table in self.table_names:
            self._parse_table(cursor, table)

    # -------------------- 内部解析逻辑 --------------------

    def _parse_table(self, cursor: sqlite3.Cursor, table: str) -> None:
        """解析单张表：字段信息 + 统计特征 + 外键 + 样例数据。"""
        self._table_fields[table] = {}
        quoted = quote_identifier(table)

        cursor.execute(f"PRAGMA table_info({quoted});")
        columns = cursor.fetchall()

        cursor.execute(f"PRAGMA foreign_key_list({quoted});")
        for fk in cursor.fetchall():
            self.foreign_keys.append({
                "constrained_table": table,
                "constrained_columns": [fk[3]],
                "referred_table": fk[2],
                "referred_columns": [fk[4]],
            })

        cursor.execute(f"SELECT COUNT(*) FROM {quoted};")
        self._row_counts[table] = cursor.fetchone()[0]

        for col in columns:
            col_name, col_type = col[1], (col[2] or "").upper()
            info = {
                "name": col_name,
                "type": col[2],
                "nullable": not col[3],
                "default": col[4],
                "primary_key": col[5],
            }

            col_quoted = quote_identifier(col_name)
            # 空值数必须用 COUNT(*) - COUNT(col)：两者都忽略 NULL，
            # 改用 COUNT(DISTINCT col) 会把“有重复值”的列误算成有空值
            cursor.execute(
                f"SELECT COUNT(DISTINCT {col_quoted}), COUNT({col_quoted}), COUNT(*), "
                f"MIN({col_quoted}), MAX({col_quoted}) FROM {quoted};"
            )
            distinct_cnt, non_null_cnt, total_cnt, min_value, max_value = cursor.fetchone()
            info["distinct"] = distinct_cnt
            info["nan_count"] = total_cnt - non_null_cnt
            info["min"] = min_value
            info["max"] = max_value

            # 抽样取值（去空），让 LLM 知道字段里真实存的是什么样子
            cursor.execute(
                f"SELECT DISTINCT {col_quoted} FROM {quoted} "
                f"WHERE {col_quoted} IS NOT NULL LIMIT 3;"
            )
            info["random"] = [short(r[0]) for r in cursor.fetchall()]

            # 文本列额外统计众数，便于识别枚举型字段
            if "CHAR" in col_type or "TEXT" in col_type:
                cursor.execute(
                    f"SELECT {col_quoted}, COUNT(*) c FROM {quoted} "
                    f"WHERE {col_quoted} IS NOT NULL "
                    f"GROUP BY {col_quoted} ORDER BY c DESC LIMIT 1;"
                )
                row = cursor.fetchone()
                info["mode"] = row[0] if row else None

            self._table_fields[table][col_name] = info

        # 样例行（前 2 行），作为 few-shot 上下文
        cursor.execute(f"SELECT * FROM {quoted} LIMIT 2;")
        self._table_rows[table] = cursor.fetchall()

    # -------------------- 对外查询接口 --------------------

    def row_count(self, table: str) -> int:
        """表的总行数。"""
        return self._row_counts.get(table, 0)

    def get_table_fields(self, table: str) -> dict[str, dict[str, Any]]:
        """指定表的字段信息与统计特征。"""
        return self._table_fields.get(table, {})

    def get_data_relations(self) -> list[dict[str, Any]]:
        """全库外键关系（表之间的连接方式）。"""
        return self.foreign_keys

    def get_table_sample(self, table: str) -> tuple[list[str], list[list[Any]]]:
        """指定表的样例行，返回 (列名, 行数据)。"""
        rows = self._table_rows.get(table, [])
        if not rows:
            return [], []
        return list(rows[0].keys()), [list(r) for r in rows]

    def describe_all_tables(self) -> str:
        """把所有表压缩成一段简介文本，供“选表”步骤使用。"""
        return "\n".join(
            f"- {table}（{self._row_counts[table]} 行）字段：{', '.join(self._table_fields[table])}"
            for table in self.table_names
        )

    def describe_table(self, table: str) -> str:
        """把单张表的 schema + 统计 + 样例渲染为文本，供“生成 SQL”使用。"""
        lines = [f"### 表 {table}（共 {self._row_counts.get(table, 0)} 行）"]
        for name, info in self._table_fields.get(table, {}).items():
            flags = []
            if info["primary_key"]:
                flags.append("PRIMARY KEY")
            if not info["nullable"]:
                flags.append("NOT NULL")
            lines.append(
                f"- {name} {info['type']} {' '.join(flags)}".rstrip()
                + f" | 唯一值:{info['distinct']} 空值:{info['nan_count']}"
                + f" 最小:{short(info['min'], 30)} 最大:{short(info['max'], 30)}"
                + f" 取值样例:{info['random']}"
            )

        cols, rows = self.get_table_sample(table)
        if rows:
            lines.append("样例数据：")
            lines.append(" | ".join(cols))
            lines.extend(" | ".join(short(v, 30) for v in r) for r in rows)
        return "\n".join(lines)

    def describe_relations(self, tables: list[str] | None = None) -> str:
        """筛选出与所选表相关的外键关系文本。"""
        selected = set(tables or self.table_names)
        lines = []
        for fk in self.foreign_keys:
            if not selected & {fk["constrained_table"], fk["referred_table"]}:
                continue
            cols = ", ".join(fk["constrained_columns"])
            # 未显式声明被引用列时，SQLite 默认引用主键
            referred = ", ".join(c for c in fk["referred_columns"] if c) or "主键"
            lines.append(f"- {fk['constrained_table']}.{cols} -> {fk['referred_table']}.{referred}")
        return "\n".join(lines) if lines else "（无外键关系）"

    # -------------------- SQL 校验与执行 --------------------

    @staticmethod
    def static_check(sql: str) -> tuple[bool, str]:
        """静态校验：只允许单条只读查询（SELECT / WITH），禁止 DML/DDL。"""
        cleaned = (sql or "").strip().rstrip(";").strip()
        if not cleaned:
            return False, "SQL 为空"

        # 先去掉注释，再把字符串/标识符字面量置空，
        # 避免字面量里的分号、关键字被误判（也避免只有注释时取首词报错）
        no_comment = re.sub(r"--.*?$|/\*.*?\*/", " ", cleaned, flags=re.M | re.S)
        no_literal = re.sub(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"", "?", no_comment)
        if ";" in no_literal:
            return False, "只允许执行单条查询，检测到多条语句（存在分号）"

        tokens = no_literal.split(None, 1)
        if not tokens:
            return False, "SQL 只有注释或空白，没有可执行语句"
        head = tokens[0].upper()
        if head not in {"SELECT", "WITH"}:
            return False, f"只允许只读查询，检测到语句类型：{head}"
        return True, "ok"

    def check_sql(self, sql: str) -> tuple[bool, str]:
        """SQL 校验：静态检查 + EXPLAIN 试跑（真正编译但不执行）。

        :return: (是否可用, 错误信息)
        """
        ok, msg = self.static_check(sql)
        if not ok:
            return False, msg
        try:
            self.conn.execute(f"EXPLAIN {sql}")
            return True, "ok"
        except sqlite3.Error as e:
            # 只保留异常摘要，方便直接回灌给 LLM 作为改写依据
            return False, f"SQL 编译失败：{type(e).__name__}: {e}"

    def execute_sql(self, sql: str) -> tuple[bool, str, list[str], list[list[Any]]]:
        """执行 SQL。

        :return: (是否成功, 错误信息, 列名列表, 数据行列表)
        """
        try:
            cursor = self.conn.execute(sql)
            cols = [d[0] for d in cursor.description] if cursor.description else []
            # 多取一行用于判断结果是否被截断
            rows = [list(r) for r in cursor.fetchmany(MAX_RESULT_ROWS + 1)]
            return True, "ok", cols, rows
        except sqlite3.Error as e:
            return False, f"SQL 执行失败：{type(e).__name__}: {e}", [], []

    def close(self) -> None:
        """显式关闭连接（只读连接，关闭后不影响数据库文件）。"""
        try:
            self.conn.close()
        except sqlite3.Error:
            pass
