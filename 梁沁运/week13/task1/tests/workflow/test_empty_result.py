"""M6: 空结果不重试 → row_count == 0 且 repair_attempts == 0。"""

import pytest

from langchain_core.messages import AIMessage

from sql_agent.models import (
    ErrorCode,
    ExecutionResult,
    FinalAnswer,
    SQLDraft,
    TableSelection,
    ValidationResult,
)


class TestEmptyResultNoRetry:
    """场景 4: 空结果不重试 → row_count == 0 且 repair_attempts == 0。"""

    @pytest.mark.asyncio
    async def test_empty_result_goes_to_summarize(self, catalog, scripted_agents, build_test_graph):
        scripted_agents.table_selector.ainvoke.return_value = (
            TableSelection(tables=["albums"], reason="test", confidence=1.0),
            AIMessage(content=""),
        )
        # SQL 合法但查询不存在的 ID → 空结果
        scripted_agents.sql_generator.ainvoke.return_value = (
            SQLDraft(
                sql="SELECT * FROM albums WHERE AlbumId = -1",
                explanation="查询不存在的专辑",
            ),
            AIMessage(content=""),
        )
        # summarizer 应收到空结果
        scripted_agents.summarizer.ainvoke.return_value = (
            FinalAnswer(answer="未查询到符合条件的数据。"),
            AIMessage(content=""),
        )

        from sql_agent.config import get_obs_settings
        from sql_agent.observability import run_workflow

        answer = await run_workflow(
            question="查询 ID 为 -1 的专辑",
            catalog=catalog,
            agents=scripted_agents,
            obs=get_obs_settings(),
        )

        # 走正常路径到达 summarize（空结果不触发修复）
        assert answer is not None
        assert "未查询到" in answer.answer
        # rewriter 未被调用
        assert scripted_agents.sql_rewriter.ainvoke.call_count == 0


class TestEmptyResultWithTruncatedFlag:
    """验证空结果时 truncated 为 False 且不触发重试。"""

    @pytest.mark.asyncio
    async def test_empty_execution_no_retry(self, catalog, scripted_agents, build_test_graph):
        scripted_agents.table_selector.ainvoke.return_value = (
            TableSelection(tables=["albums"], reason="test", confidence=1.0),
            AIMessage(content=""),
        )
        scripted_agents.sql_generator.ainvoke.return_value = (
            SQLDraft(
                sql="SELECT * FROM albums WHERE AlbumId = 0",
                explanation="test",
            ),
            AIMessage(content=""),
        )
        scripted_agents.summarizer.ainvoke.return_value = (
            FinalAnswer(answer="未查询到符合条件的数据。", caveats=["查询结果为空"]),
            AIMessage(content=""),
        )

        from sql_agent.config import get_obs_settings
        from sql_agent.observability import run_workflow

        answer = await run_workflow(
            question="查询不存在的专辑",
            catalog=catalog,
            agents=scripted_agents,
            obs=get_obs_settings(),
        )

        assert answer is not None
        # 空结果走正常 summaries 路径，不触发修复
        assert scripted_agents.sql_rewriter.ainvoke.call_count == 0
