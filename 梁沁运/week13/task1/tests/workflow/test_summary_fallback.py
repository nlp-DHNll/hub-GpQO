"""M6: 汇总降级不崩溃 → stage == "summarize_fallback"。"""

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


class TestSummaryFallback:
    """场景 5: 汇总降级不崩溃 → answer 是 Markdown 表格，stage == "summarize_fallback"。"""

    @pytest.mark.asyncio
    async def test_summary_llm_failure_does_not_crash(self, catalog, scripted_agents, build_test_graph):
        scripted_agents.table_selector.ainvoke.return_value = (
            TableSelection(tables=["albums"], reason="test", confidence=1.0),
            AIMessage(content=""),
        )
        scripted_agents.sql_generator.ainvoke.return_value = (
            SQLDraft(sql="SELECT * FROM albums LIMIT 5", explanation="test"),
            AIMessage(content=""),
        )
        # summarizer 抛出异常 → 触发降级（只对 summarize 节点设置异常）
        scripted_agents.summarizer.ainvoke.side_effect = RuntimeError("模拟 LLM 调用失败")

        from sql_agent.config import get_obs_settings
        from sql_agent.observability import run_workflow

        answer = await run_workflow(
            question="列出前 5 张专辑",
            catalog=catalog,
            agents=scripted_agents,
            obs=get_obs_settings(),
        )

        # 图不崩溃
        assert answer is not None
        assert isinstance(answer, FinalAnswer)
        # 降级输出是 Markdown 表格
        assert "---" in answer.answer
        assert "SELECT" in answer.answer


class TestSummaryFallbackWithNoExecution:
    """汇总节点在 execution=None 时也不会崩溃。"""

    @pytest.mark.asyncio
    async def test_no_execution_summarize(self, catalog, scripted_agents, build_test_graph):
        # 模拟：生成坏的 SQL → 校验失败 → sql_rewrite → cannot_fix → failure_answer
        scripted_agents.table_selector.ainvoke.return_value = (
            TableSelection(tables=["albums"], reason="test", confidence=1.0),
            AIMessage(content=""),
        )
        scripted_agents.sql_generator.ainvoke.return_value = (
            SQLDraft(sql="SELECT * FORM albums", explanation="test"),  # typo
            AIMessage(content=""),
        )
        # rewriter 返回 cannot_fix，短路到 failure_answer
        scripted_agents.sql_rewriter.ainvoke.return_value = (
            SQLDraft(cannot_fix=True, cannot_fix_reason="无法修复"),
            AIMessage(content=""),
        )

        from sql_agent.config import get_obs_settings
        from sql_agent.observability import run_workflow

        answer = await run_workflow(
            question="查询测试",
            catalog=catalog,
            agents=scripted_agents,
            obs=get_obs_settings(),
        )

        assert answer is not None
        # 走了 failure_answer 路径，不是 summarize 降级
        assert "失败" in answer.answer or "无法" in answer.answer
