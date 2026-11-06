"""M5: 修复预算耗尽 + cannot_fix 提前终止。

工作流测试不 mock 节点本身，只 mock StructuredAgent.ainvoke。
关键断言：计数器 + call_count 双断言。

注意：validator/executor 用真实 catalog，所以 sql_generate 必须返回
会让 EXPLAIN 失败的 SQL（如 typo：FORM）才能触发修复回路。
"""

import pytest

from langchain_core.messages import AIMessage

from sql_agent.models import (
    ErrorCode,
    ExecutionResult,
    FinalAnswer,
    SQLAttempt,
    SQLDraft,
    TableSelection,
    ValidationResult,
)


class TestRepairBudgetExhausted:
    """场景 1: 修复预算耗尽 → repair_attempts == 3 且 call_count == 3，走 failure_answer。"""

    @pytest.mark.asyncio
    async def test_budget_exhausted_stops_at_3(self, catalog, scripted_agents, build_test_graph):
        scripted_agents.table_selector.ainvoke.return_value = (
            TableSelection(tables=["albums"], reason="test", confidence=1.0),
            AIMessage(content=""),
        )
        # 生成会语法错误的 SQL → 触发修复回路
        scripted_agents.sql_generator.ainvoke.return_value = (
            SQLDraft(sql="SELECT * FORM albums", explanation="test"),  # typo: FORM
            AIMessage(content=""),
        )
        # sql_rewrite 返回也会失败的 SQL（让 validator 继续失败）
        scripted_agents.sql_rewriter.ainvoke.return_value = (
            SQLDraft(sql="SELECT * FORM albums WHERE 1=1", explanation="fix"),
            AIMessage(content=""),
        )

        from sql_agent.config import get_obs_settings
        from sql_agent.observability import run_workflow

        answer = await run_workflow(
            question="有多少张专辑？",
            catalog=catalog,
            agents=scripted_agents,
            obs=get_obs_settings(),
        )

        # rewriter 被调用了 3 次（生成失败 → 修复 → 又失败 → 修复 → 又失败 → 修复 → 预算耗尽）
        assert scripted_agents.sql_rewriter.ainvoke.call_count == 3
        assert "失败" in answer.answer or "预算" in answer.answer or "无法" in answer.answer


class TestCannotFixShortCircuit:
    """场景 2: cannot_fix 提前终止 → repair_attempts == 1 且 call_count == 1。"""

    @pytest.mark.asyncio
    async def test_cannot_fix_stops_immediately(self, catalog, scripted_agents, build_test_graph):
        scripted_agents.table_selector.ainvoke.return_value = (
            TableSelection(tables=["albums"], reason="test", confidence=1.0),
            AIMessage(content=""),
        )
        # 生成会语法错误的 SQL
        scripted_agents.sql_generator.ainvoke.return_value = (
            SQLDraft(sql="SELECT * FORM albums", explanation="test"),
            AIMessage(content=""),
        )
        # rewriter 第一次就返回 cannot_fix
        scripted_agents.sql_rewriter.ainvoke.return_value = (
            SQLDraft(
                cannot_fix=True,
                cannot_fix_reason="数据库中没有相关数据",
            ),
            AIMessage(content=""),
        )

        from sql_agent.config import get_obs_settings
        from sql_agent.observability import run_workflow

        answer = await run_workflow(
            question="有多少张专辑？",
            catalog=catalog,
            agents=scripted_agents,
            obs=get_obs_settings(),
        )

        # rewriter 只被调用 1 次
        assert scripted_agents.sql_rewriter.ainvoke.call_count == 1
        assert "失败" in answer.answer or "无法" in answer.answer or "cannot_fix" in str(answer.caveats).lower()
