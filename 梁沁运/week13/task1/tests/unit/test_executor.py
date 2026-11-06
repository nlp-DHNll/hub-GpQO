"""M2: test_executor.py — SQLExecutor 单元测试。用 tmp_path 临时 DB，不碰 ref/chinook.db。"""

import pytest

from sqlalchemy import create_engine

from sql_agent.db.executor import SQLExecutor
from sql_agent.models import ErrorCode, ExecutionResult


@pytest.fixture
def tmp_engine(tmp_db):
    return create_engine(f"sqlite:///{tmp_db}")


@pytest.fixture
def executor(tmp_engine):
    return SQLExecutor(tmp_engine)


class TestSQLExecutor:

    def test_select_all_returns_rows(self, executor):
        result = executor.execute("SELECT * FROM test_t")
        assert isinstance(result, ExecutionResult)
        assert result.row_count == 3
        assert result.columns == ["id", "name"]
        assert len(result.rows) == 3

    def test_truncation_at_limit(self, tmp_engine):
        """超过 MAX_EXECUTION_ROWS 时截断。"""
        # 创建更多数据
        with tmp_engine.connect() as conn:
            from sqlalchemy import text
            for i in range(250):
                conn.execute(text(f"INSERT INTO test_t VALUES ({i+10}, 'User{i}')"))
            conn.commit()

        executor = SQLExecutor(tmp_engine)
        result = executor.execute("SELECT * FROM test_t")
        assert isinstance(result, ExecutionResult)
        assert result.truncated
        assert result.row_count <= 210  # 考虑已有 3 行 + 250 新行

    def test_nonexistent_table_error(self, executor):
        result = executor.execute("SELECT * FROM no_such_table")
        assert isinstance(result, tuple)
        _, validation = result
        assert not validation.ok
        assert validation.code == ErrorCode.UNKNOWN_OBJECT

    def test_syntax_error(self, executor):
        result = executor.execute("SELEC * FROM test_t")
        assert isinstance(result, tuple)
        _, validation = result
        assert not validation.ok

    def test_rows_are_strings(self, executor):
        result = executor.execute("SELECT * FROM test_t")
        assert isinstance(result, ExecutionResult)
        for row in result.rows:
            for cell in row:
                assert isinstance(cell, str)

    def test_null_handling(self, tmp_engine):
        with tmp_engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("INSERT INTO test_t VALUES (4, NULL)"))
            conn.commit()

        executor = SQLExecutor(tmp_engine)
        result = executor.execute("SELECT * FROM test_t WHERE id = 4")
        assert isinstance(result, ExecutionResult)
        assert "NULL" in result.rows[0]
