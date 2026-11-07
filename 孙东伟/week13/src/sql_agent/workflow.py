"""对外入口：把 LangGraph 的最终状态组装成稳定 JSON。

真正的流程编排在 ``graph.py``（LangGraph ``StateGraph``）。这里只保留
CLI 需要的三件事：输入校验、异常兜底、``WorkflowOutput`` 组装。
"""

from __future__ import annotations

import logging
import time

from .config import settings
from .db.catalog import SchemaCatalog
from .db.executor import SQLExecutor
from .db.validator import SQLValidator
from .graph import SQLAgentGraph
from .models import FinalAnswer, WorkflowOutput

logger = logging.getLogger(__name__)


class SQLAgentWorkflow:
    """LangGraph 图的薄封装，保持与 CLI / 测试一致的调用方式。"""

    def __init__(
        self,
        catalog: SchemaCatalog | None = None,
        validator: SQLValidator | None = None,
        executor: SQLExecutor | None = None,
        *,
        max_repair_attempts: int | None = None,
    ) -> None:
        self.agent_graph = SQLAgentGraph(
            catalog=catalog,
            validator=validator,
            executor=executor,
            max_repair_attempts=max_repair_attempts,
        )

    async def run(self, question: str) -> WorkflowOutput:
        if not isinstance(question, str):
            raise TypeError("question 必须是字符串")
        question = question.strip()
        if not question:
            logger.warning("workflow ignored empty question")
            return WorkflowOutput(question=question, answer="请输入要查询的问题。")

        started = time.perf_counter()
        logger.info(
            "workflow started question=%s primary_model=%s summary_model=%s",
            _preview(question, 300),
            settings.primary_model,
            settings.summary_model,
        )
        try:
            state = await self.agent_graph.ainvoke(question)
            result = self._to_output(state)
            logger.info(
                "workflow finished elapsed=%.2fs status=%s tables=%s rows=%s repairs=%s error=%s",
                time.perf_counter() - started,
                result.status,
                result.tables,
                result.row_count,
                result.repair_attempts,
                result.error,
            )
            return result
        except Exception as exc:
            logger.exception("SQL agent workflow failed")
            return WorkflowOutput(
                question=question,
                answer=f"处理失败：{exc}",
                error=str(exc),
                status="failed",
            )

    @staticmethod
    def _to_output(state: dict) -> WorkflowOutput:
        """把图状态转换为面向用户的 JSON，字段全部由代码填写。"""

        execution = state.get("execution")
        answer = state.get("answer") or FinalAnswer(answer="处理失败：未生成答案。")
        return WorkflowOutput(
            question=state.get("question", ""),
            answer=answer.answer,
            sql=state.get("sql"),
            tables=state.get("tables", []),
            row_count=execution.row_count if execution is not None else 0,
            truncated=execution.truncated if execution is not None else False,
            columns=execution.columns if execution is not None else [],
            rows=execution.rows if execution is not None else [],
            repair_attempts=state.get("repair_attempts", 0),
            evidence=answer.evidence,
            caveats=answer.caveats,
            error=state.get("error"),
            status=state.get("status", "ok"),
        )


def _preview(text: str, limit: int = 2000) -> str:
    compact = " ".join(str(text).split())
    return compact if len(compact) <= limit else compact[:limit] + "..."
