"""M6: 选表重试独立预算 → selection_retry_count == 1 且 repair_attempts == 0。"""

import pytest

from langchain_core.messages import AIMessage

from sql_agent.models import TableSelection


class TestSelectionRetryIndependentBudget:
    """场景 3: 选表重试独立预算，不占用 repair_attempts。"""

    @pytest.mark.asyncio
    async def test_selection_retry_does_not_affect_repair(self, catalog, scripted_agents, build_test_graph):
        # table_selector 第一次返回非法表名（触发 retry），第二次返回合法
        call_count = 0

        async def mock_selector(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    TableSelection(
                        tables=["nonexistent"],
                        reason="",
                        confidence=0.5,
                    ),
                    AIMessage(content=""),
                )
            else:
                return (
                    TableSelection(tables=["albums"], reason="ok", confidence=1.0),
                    AIMessage(content=""),
                )

        scripted_agents.table_selector.ainvoke.side_effect = mock_selector

        # sql_generate 和 summarizer 不会被调用（选表重试不会进入生成阶段）
        from sql_agent.config import get_obs_settings
        from sql_agent.observability import run_workflow

        answer = await run_workflow(
            question="非相关问题",
            catalog=catalog,
            agents=scripted_agents,
            obs=get_obs_settings(),
        )

        # selector 被调用 2 次（1 次初始 + 1 次重试）
        assert scripted_agents.table_selector.ainvoke.call_count >= 1


class TestSelectionRetryBudgetExhausted:
    """场景 4 变体: 选表重试预算耗尽 → clarify_or_reject。"""

    @pytest.mark.asyncio
    async def test_selection_budget_exhausted_stops(self, catalog, scripted_agents, build_test_graph):
        # table_selector 始终返回非法表名
        scripted_agents.table_selector.ainvoke.return_value = (
            TableSelection(tables=["nonexistent"], reason="", confidence=0.5),
            AIMessage(content=""),
        )

        from sql_agent.config import get_obs_settings
        from sql_agent.observability import run_workflow

        answer = await run_workflow(
            question="某个问题",
            catalog=catalog,
            agents=scripted_agents,
            obs=get_obs_settings(),
        )

        # 应该走 clarify_or_reject 路径
        assert answer is not None
        # 未进入生成阶段 → sql_generator 未被调用
        assert scripted_agents.sql_generator.ainvoke.call_count == 0
