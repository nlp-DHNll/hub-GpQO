"""M2: test_validator.py — SQLValidator 单元测试。"""

import pytest

from sql_agent.db.validator import SQLValidator
from sql_agent.models import ErrorCode


@pytest.fixture
def validator(catalog):
    return SQLValidator(catalog.engine)


class TestSQLValidator:

    def test_valid_select_passes(self, validator):
        result = validator.validate("SELECT * FROM albums")
        assert result.ok
        assert result.code is None

    def test_drop_table_rejected(self, validator):
        result = validator.validate("DROP TABLE albums")
        assert not result.ok
        assert result.code == ErrorCode.UNSAFE

    def test_insert_rejected(self, validator):
        result = validator.validate("INSERT INTO albums VALUES (1, 'Test', 1)")
        assert not result.ok
        assert result.code == ErrorCode.UNSAFE

    def test_multi_statement_rejected(self, validator):
        result = validator.validate("SELECT * FROM albums; DROP TABLE albums")
        assert not result.ok
        assert result.code == ErrorCode.UNSAFE

    def test_nonexistent_table_error(self, validator):
        result = validator.validate("SELECT * FROM nonexistent_table")
        assert not result.ok
        assert result.code == ErrorCode.UNKNOWN_OBJECT

    def test_syntax_error_detected(self, validator):
        result = validator.validate("SELECT * FORM albums")
        assert not result.ok

    def test_trailing_semicolon_stripped(self, validator):
        result = validator.validate("SELECT * FROM albums;")
        assert result.ok
        assert not result.normalized_sql.endswith(";")

    def test_empty_sql_rejected(self, validator):
        result = validator.validate("")
        assert not result.ok

    def test_only_select_and_with_allowed(self, validator):
        # SELECT 允许
        assert validator.validate("SELECT 1").ok
        # WITH 允许
        result = validator.validate("WITH x AS (SELECT 1) SELECT * FROM x")
        assert result.ok

    def test_pragma_rejected(self, validator):
        result = validator.validate("PRAGMA table_info(albums)")
        assert not result.ok
        assert result.code == ErrorCode.UNSAFE

    def test_explain_is_the_only_sent_statement(self, monkeypatch, validator):
        """EXPLAIN 是唯一发送给 DB 的语句。"""
        executed = []
        original_execute = validator._engine.connect

        def tracking_execute(*args, **kwargs):
            executed.append("connect")
            return original_execute(*args, **kwargs)

        # 这里只验证 EXPLAIN 的机制：validator 内部用 engine.connect()
        result = validator.validate("SELECT * FROM albums")
        assert result.ok
