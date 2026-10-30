import asyncio
from pathlib import Path

import pytest

from sql_agent.config import settings
from sql_agent.db.catalog import SchemaCatalog
from sql_agent.db.executor import SQLExecutor
from sql_agent.db.validator import SQLValidator
from sql_agent.models import FinalAnswer, SQLDraft, TableSelection
from sql_agent.workflow import SQLAgentWorkflow
import sql_agent.workflow as workflow_module


class FakeChain:
    """替代 LangChain Runnable：从共享队列按调用顺序弹出一个结构化结果。"""

    def __init__(self, queue, calls):
        self._queue = queue
        self._calls = calls

    async def ainvoke(self, input, **kwargs):
        self._calls.append(input.get("input"))
        return self._queue.pop(0)


@pytest.fixture(scope="module")
def workflow() -> SQLAgentWorkflow:
    catalog = SchemaCatalog(Path("ref/chinook.db"))
    return SQLAgentWorkflow(
        catalog=catalog,
        validator=SQLValidator(catalog.db_path),
        executor=SQLExecutor(catalog.db_path),
    )


def _patch_chains(monkeypatch, outputs):
    """把 workflow 里四个 get_*_chain() 全部替换为共享队列的 FakeChain。"""

    calls = []
    queue = list(outputs)

    def make_fake():
        return FakeChain(queue, calls)

    monkeypatch.setattr(workflow_module, "get_table_selector_chain", make_fake)
    monkeypatch.setattr(workflow_module, "get_sql_generator_chain", make_fake)
    monkeypatch.setattr(workflow_module, "get_sql_rewriter_chain", make_fake)
    monkeypatch.setattr(workflow_module, "get_result_summary_chain", make_fake)
    return calls


def test_happy_path(workflow: SQLAgentWorkflow, monkeypatch) -> None:
    outputs = [
        TableSelection(tables=["albums"], reason="统计专辑数量", confidence=0.9),
        SQLDraft(sql="SELECT COUNT(*) AS n FROM albums", explanation="count"),
        FinalAnswer(answer="共 347 张专辑。", evidence=["347"]),
    ]
    calls = _patch_chains(monkeypatch, outputs)

    result = asyncio.run(workflow.run("总共有多少张专辑？"))

    assert result.error is None
    assert result.tables == ["albums"]
    assert result.row_count == 1
    assert result.answer == "共 347 张专辑。"
    assert len(calls) == 3


def test_rewrite_path(workflow: SQLAgentWorkflow, monkeypatch) -> None:
    outputs = [
        TableSelection(tables=["albums"], reason="统计专辑数量", confidence=0.9),
        SQLDraft(sql="SELECT COUNT(ArtistId FROM albums", explanation="bad"),
        SQLDraft(sql="SELECT COUNT(ArtistId) AS n FROM albums", explanation="fixed"),
        FinalAnswer(answer="共有 275 位艺人。", evidence=["275"]),
    ]
    calls = _patch_chains(monkeypatch, outputs)

    result = asyncio.run(workflow.run("专辑里有多少位不同的艺人？"))

    assert result.repair_attempts == 1
    assert result.error is None
    assert "COUNT(ArtistId)" in (result.sql or "")
    assert len(calls) == 4


def test_empty_result_skips_summary_agent(workflow: SQLAgentWorkflow, monkeypatch) -> None:
    outputs = [
        TableSelection(tables=["albums"], reason="查不存在的专辑", confidence=0.9),
        SQLDraft(sql="SELECT * FROM albums WHERE AlbumId = -1", explanation="empty"),
    ]
    calls = _patch_chains(monkeypatch, outputs)

    result = asyncio.run(workflow.run("编号为 -1 的专辑是什么？"))

    assert result.row_count == 0
    assert result.answer == "未查询到符合条件的数据。"
    assert len(calls) == 2


def test_unknown_table_is_rejected(workflow: SQLAgentWorkflow, monkeypatch) -> None:
    outputs = [
        TableSelection(tables=["not_a_table"], reason="bad", confidence=0.1),
        TableSelection(tables=["albums"], reason="fixed", confidence=0.9),
        SQLDraft(sql="SELECT COUNT(*) AS n FROM albums", explanation="count"),
        FinalAnswer(answer="共 347 张专辑。", evidence=["347"]),
    ]
    calls = _patch_chains(monkeypatch, outputs)

    result = asyncio.run(workflow.run("总共有多少张专辑？"))

    assert result.error is None
    assert result.tables == ["albums"]
    assert len(calls) == 4


def test_max_repair_attempts_returns_error(monkeypatch) -> None:
    catalog = SchemaCatalog(Path("ref/chinook.db"))
    workflow = SQLAgentWorkflow(
        catalog=catalog,
        validator=SQLValidator(catalog.db_path),
        executor=SQLExecutor(catalog.db_path),
        max_repair_attempts=0,
    )
    outputs = [
        TableSelection(tables=["albums"], reason="bad sql", confidence=0.9),
        SQLDraft(sql="SELECT nope FROM albums", explanation="bad"),
    ]
    calls = _patch_chains(monkeypatch, outputs)

    result = asyncio.run(workflow.run("测试失败路径"))

    assert result.error is not None
    assert result.repair_attempts == 0
    assert "最大修复次数" in result.answer
    assert len(calls) == 2


def test_settings_db_path_exists() -> None:
    assert settings.db_path.exists()
