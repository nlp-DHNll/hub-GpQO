"""M1: test_catalog.py — SchemaCatalog 单元测试。"""

import pytest

from sql_agent.db.catalog import BUSINESS_TABLES


class TestSchemaCatalog:
    """catalog fixture 是 session 级，真实 ref/chinook.db。"""

    def test_only_business_tables_exposed(self, catalog):
        """只暴露 11 张业务表。"""
        for t in catalog.table_names:
            assert t in BUSINESS_TABLES, f"{t} 不在业务表白名单"
        assert len(catalog.table_names) == 11

    def test_render_catalog_contains_tables(self, catalog):
        text = catalog.render_catalog()
        assert "albums" in text
        assert "customers" in text
        assert "invoices" in text

    def test_render_schema_has_3_sample_rows(self, catalog):
        """render_schema 含 3 行样例。"""
        text = catalog.render_schema(["albums"])
        assert "样例" in text
        # 应提及样例数据

    def test_render_schema_includes_join_edges(self, catalog):
        text = catalog.render_schema(["albums", "artists"])
        assert "JOIN 关系" in text
        assert "ArtistId" in text

    def test_is_connected_single_table(self, catalog):
        assert catalog.is_connected(["albums"])
        assert catalog.is_connected(["customers"])

    def test_is_connected_related_tables(self, catalog):
        assert catalog.is_connected(["albums", "artists"])
        assert catalog.is_connected(["tracks", "albums", "artists"])

    def test_is_connected_disconnected_tables(self, catalog):
        # albums 和 customers 之间没有直接或间接 FK
        assert not catalog.is_connected(["albums", "customers"])

    def test_row_counts_positive(self, catalog):
        for t in catalog.table_names:
            assert catalog.row_counts[t] > 0, f"{t} 行数为 0"

    def test_column_info_complete(self, catalog):
        for t in catalog.table_names:
            cols = catalog.columns[t]
            assert len(cols) > 0, f"{t} 没有列信息"
            for c in cols:
                assert "name" in c
                assert "type" in c

    def test_cache_hit(self, catalog):
        """缓存命中：load 再次调用不重复解析。"""
        import time
        start = time.perf_counter()
        catalog.load()
        elapsed = time.perf_counter() - start
        # 缓存命中应远小于首次加载
        assert elapsed < 0.1, f"缓存命中耗时 {elapsed:.3f}s"
