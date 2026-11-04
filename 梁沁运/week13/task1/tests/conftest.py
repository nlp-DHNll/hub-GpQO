"""pytest fixtures：catalog (session), scripted_agents (function), build_test_graph, tmp_db。"""

import os
import sys

import pytest

# 确保 src/ 在 path 中
_src = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _src)


@pytest.fixture(scope="session")
def db_path():
    """ref/chinook.db 的绝对路径。"""
    return os.path.join(
        os.path.dirname(__file__), "..", "ref", "chinook.db"
    )


@pytest.fixture(scope="session")
def catalog(db_path):
    """session 级 SchemaCatalog，真实 ref/chinook.db，不 mock。"""
    from sql_agent.db.catalog import SchemaCatalog

    c = SchemaCatalog(db_path)
    c.load()
    return c


@pytest.fixture
def scripted_agents():
    """function 级四个 Agent 的 AsyncMock。"""
    from unittest.mock import AsyncMock, MagicMock

    class ScriptedAgents:
        def __init__(self):
            self.table_selector = AsyncMock()
            self.sql_generator = AsyncMock()
            self.sql_rewriter = AsyncMock()
            self.summarizer = AsyncMock()
            # build_messages 也 mock：返回简单列表
            for ag in [self.table_selector, self.sql_generator,
                       self.sql_rewriter, self.summarizer]:
                ag.build_messages = MagicMock(return_value=[])

    return ScriptedAgents()


@pytest.fixture
def build_test_graph(catalog, scripted_agents):
    """返回工厂函数，生成未 compile 的图（可选用 InMemorySaver）。"""
    from sql_agent.graph import build_graph

    def _build():
        return build_graph(catalog, scripted_agents)

    return _build


@pytest.fixture
def tmp_db(tmp_path):
    """function 级临时 SQLite DB，供 executor 测试，不碰 ref/chinook.db。"""
    import sqlite3

    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE test_t (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO test_t VALUES (1, 'Alice'), (2, 'Bob'), (3, 'Charlie')")
    conn.commit()
    conn.close()
    return str(db_file)
