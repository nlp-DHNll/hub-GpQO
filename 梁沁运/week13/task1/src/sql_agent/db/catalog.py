"""SchemaCatalog — 解析 SQLite DB、缓存 schema/统计/外键/样例。

进程级单例，按 DB mtime 失效。不实现 check_sql。
提供两种渲染视图：render_catalog()（选表用）、render_schema(tables)（生成/修复用）。
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

# Chinook 的 11 张业务表
BUSINESS_TABLES = frozenset({
    "albums", "artists", "customers", "employees", "genres",
    "invoice_items", "invoices", "media_types", "playlist_track",
    "playlists", "tracks",
})

# 排除的内部表前缀
INTERNAL_TABLE_PREFIXES = ("sqlite_",)


class SchemaCatalog:
    """数据库 schema 信息缓存。"""

    # 解析结果（在 load() 中填充）
    table_names: list[str] = []
    columns: dict[str, list[dict[str, Any]]] = {}   # table → [col_info]
    row_counts: dict[str, int] = {}                 # table → count
    fk_edges: list[tuple[str, str, str, str]] = []  # (from_t, from_c, to_t, to_c)
    _adj: dict[str, set[str]] = None  # type: ignore  # 无向邻接

    def __init__(self, db_path: str, *, readonly: bool = True):
        self._db_path = os.path.abspath(db_path)
        self._readonly = readonly
        self._engine: Engine | None = None
        self._mtime: float = 0.0
        self._loaded: bool = False
        # 重置解析结果
        self.table_names = []
        self.columns = {}
        self.row_counts = {}
        self.fk_edges = []
        self._adj = defaultdict(set)

    @property
    def engine(self) -> Engine:
        """公开引擎引用，供 validator / executor 使用。"""
        return self._get_engine()

    # ------------------------------------------------------------------
    # 引擎
    # ------------------------------------------------------------------
    def _get_engine(self) -> Engine:
        if self._engine is None:
            db_uri = self._db_path.replace("\\", "/")
            if self._readonly:
                url = f"sqlite:///file:{db_uri}?mode=ro&uri=true"
            else:
                url = f"sqlite:///{db_uri}"
            self._engine = create_engine(url)
        return self._engine

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def _needs_reload(self) -> bool:
        if not self._loaded:
            return True
        try:
            current_mtime = os.path.getmtime(self._db_path)
            return current_mtime != self._mtime
        except OSError:
            return True

    def load(self) -> None:
        """解析 DB（若缓存有效则跳过）。初始化约 0.8 秒。"""
        if not self._needs_reload():
            return

        engine = self._get_engine()
        inspector = inspect(engine)
        all_tables = inspector.get_table_names()

        # 过滤：只保留 11 张业务表
        self.table_names = sorted(
            t for t in all_tables
            if not t.startswith(INTERNAL_TABLE_PREFIXES) and t in BUSINESS_TABLES
        )

        self.columns.clear()
        self.row_counts.clear()
        self.fk_edges.clear()
        self._adj.clear()

        for table in self.table_names:
            # 列信息
            col_infos: list[dict[str, Any]] = []
            for col in inspector.get_columns(table):
                info = {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "primary_key": bool(col.get("primary_key")),
                }
                # 统计
                stats = self._column_stats(table, col["name"])
                info.update(stats)
                col_infos.append(info)
            self.columns[table] = col_infos

            # 行数
            self.row_counts[table] = self._count_rows(table)

        # 外键
        for table in self.table_names:
            for fk in inspector.get_foreign_keys(table):
                from_col = fk["constrained_columns"][0] if fk["constrained_columns"] else ""
                to_table = fk["referred_table"]
                to_col = fk["referred_columns"][0] if fk["referred_columns"] else ""
                if to_table in BUSINESS_TABLES:
                    edge = (table, from_col, to_table, to_col)
                    self.fk_edges.append(edge)
                    self._adj[table].add(to_table)
                    self._adj[to_table].add(table)

        self._mtime = os.path.getmtime(self._db_path)
        self._loaded = True

    # ------------------------------------------------------------------
    # 列统计
    # ------------------------------------------------------------------
    def _column_stats(self, table: str, column: str) -> dict[str, Any]:
        engine = self._get_engine()
        col_quoted = f'"{column}"'
        tbl_quoted = f'"{table}"'

        with engine.connect() as conn:
            # distinct
            try:
                distinct = conn.execute(
                    text(f"SELECT COUNT(DISTINCT {col_quoted}) FROM {tbl_quoted}")
                ).scalar()
            except Exception:
                distinct = None

            # 缺失数
            try:
                nulls = conn.execute(
                    text(f"SELECT COUNT(*) FROM {tbl_quoted} WHERE {col_quoted} IS NULL")
                ).scalar()
            except Exception:
                nulls = None

            # min / max
            try:
                row = conn.execute(
                    text(f"SELECT MIN({col_quoted}), MAX({col_quoted}) FROM {tbl_quoted}")
                ).fetchone()
                cmin, cmax = (str(row[0]) if row[0] is not None else None,
                              str(row[1]) if row[1] is not None else None)
            except Exception:
                cmin, cmax = None, None

            # mode（众数）
            try:
                mode_row = conn.execute(
                    text(
                        f"SELECT {col_quoted}, COUNT(*) AS cnt "
                        f"FROM {tbl_quoted} "
                        f"WHERE {col_quoted} IS NOT NULL "
                        f"GROUP BY {col_quoted} ORDER BY cnt DESC LIMIT 1"
                    )
                ).fetchone()
                mode = str(mode_row[0]) if mode_row else None
            except Exception:
                mode = None

            # 3 行样例
            try:
                sample_rows = conn.execute(
                    text(f"SELECT {col_quoted} FROM {tbl_quoted} WHERE {col_quoted} IS NOT NULL LIMIT 3")
                ).fetchall()
                sample = [str(r[0]) for r in sample_rows]
            except Exception:
                sample = []

        return {
            "distinct": distinct,
            "nulls": nulls,
            "min": cmin,
            "max": cmax,
            "mode": mode,
            "sample_3": sample,
        }

    # ------------------------------------------------------------------
    # 行数
    # ------------------------------------------------------------------
    def _count_rows(self, table: str) -> int:
        engine = self._get_engine()
        with engine.connect() as conn:
            return conn.execute(
                text(f'SELECT COUNT(*) FROM "{table}"')
            ).scalar() or 0

    # ------------------------------------------------------------------
    # 连通性
    # ------------------------------------------------------------------
    def is_connected(self, tables: list[str]) -> bool:
        """判断表集合在 FK 无向图中是否连通。单表总是连通。"""
        if len(tables) <= 1:
            return True
        target = set(tables)
        visited: set[str] = set()
        stack = [tables[0]]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            for nb in self._adj.get(cur, set()):
                if nb in target and nb not in visited:
                    stack.append(nb)
        return target.issubset(visited)

    # ------------------------------------------------------------------
    # 渲染视图
    # ------------------------------------------------------------------
    def render_catalog(self) -> str:
        """为 table_select 提供目录摘要。"""
        lines: list[str] = []
        lines.append("=== 数据库目录 ===")
        for table in self.table_names:
            cols = [c["name"] for c in self.columns.get(table, [])]
            lines.append(
                f"- {table} (行数: {self.row_counts.get(table, '?')}, "
                f"列: {', '.join(cols)})"
            )

        if self.fk_edges:
            lines.append("\n=== 外键关系 ===")
            for from_t, from_c, to_t, to_c in self.fk_edges:
                lines.append(f"  {from_t}.{from_c} → {to_t}.{to_c}")
        return "\n".join(lines)

    def render_schema(self, tables: list[str]) -> str:
        """为 sql_generate / sql_rewrite 提供详细 schema + 3 行样例 + JOIN 边。"""
        lines: list[str] = []
        lines.append(f"=== 已选表详细 Schema: {', '.join(tables)} ===")

        for table in tables:
            if table not in self.columns:
                continue
            lines.append(f"\n--- {table} (行数: {self.row_counts.get(table, '?')}) ---")
            for col in self.columns[table]:
                stats_parts = []
                if col.get("distinct") is not None:
                    stats_parts.append(f"distinct={col['distinct']}")
                if col.get("nulls") is not None:
                    stats_parts.append(f"nulls={col['nulls']}")
                if col.get("min") is not None:
                    stats_parts.append(f"min={col['min']}")
                if col.get("max") is not None:
                    stats_parts.append(f"max={col['max']}")
                if col.get("mode") is not None:
                    stats_parts.append(f"mode={col['mode']}")
                stats_str = ", ".join(stats_parts) if stats_parts else ""

                line = (
                    f"  {col['name']}  {col['type']}  "
                    f"{'NULL' if col['nullable'] else 'NOT NULL'}"
                )
                if stats_str:
                    line += f"  [{stats_str}]"
                if col.get("sample_3"):
                    samples = ", ".join(col["sample_3"])
                    line += f"  样例: {samples}"
                lines.append(line)

        # 所选表之间的 JOIN 边
        table_set = set(tables)
        relevant_fks = [
            (ft, fc, tt, tc) for ft, fc, tt, tc in self.fk_edges
            if ft in table_set and tt in table_set
        ]
        if relevant_fks:
            lines.append("\n=== 所选表之间的 JOIN 关系 ===")
            for ft, fc, tt, tc in relevant_fks:
                lines.append(f"  {ft}.{fc} → {tt}.{tc}")

        lines.append("\n【方言说明】目标数据库为 SQLite。")
        return "\n".join(lines)