"""图执行器：一次性运行 + 流式阶段事件（供 CLI / SSE 使用）。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from langgraph.graph.state import CompiledStateGraph

from ..config import settings
from ..db.catalog import SchemaCatalog, get_catalog
from ..db.executor import SQLExecutor
from ..db.validator import SQLValidator
from ..models import WorkflowOutput
from .builder import build_sql_agent_graph
from .nodes import NODE_LABELS

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 50


def initial_state(question: str, max_repair_attempts: int) -> dict:
    return {
        "question": question,
        "max_repair_attempts": max_repair_attempts,
        "tables": [],
        "attempts": [],
        "repair_attempts": 0,
        "select_attempts": 0,
        "select_feedback": "",
        "stages": [],
    }


def _event_detail(update: dict | None) -> dict:
    stages = (update or {}).get("stages") or []
    return stages[-1].get("detail", {}) if stages else {}


class SQLAgentGraph:
    """对编译后的图做一层薄封装：稳定输出契约 + 阶段事件。"""

    def __init__(
        self,
        graph: CompiledStateGraph,
        *,
        max_repair_attempts: int | None = None,
    ) -> None:
        self.graph = graph
        self.max_repair_attempts = (
            settings.max_repair_attempts
            if max_repair_attempts is None
            else max_repair_attempts
        )

    async def run(self, question: str) -> WorkflowOutput:
        """只返回对外契约（CLI / 集成调用方使用）。"""

        result = await self.run_full(question)
        return result["output"]

    async def run_full(self, question: str) -> dict:
        """返回答案 + 结果行 + 阶段时间线（网页接口使用）。"""

        if not isinstance(question, str):
            raise TypeError("question 必须是字符串")
        question = question.strip()
        if not question:
            output = WorkflowOutput(question=question, answer="请输入要查询的问题。")
            return {
                "output": output,
                "columns": [],
                "rows": [],
                "stages": [],
            }

        state = initial_state(question, self.max_repair_attempts)
        try:
            final_state = await self.graph.ainvoke(
                state, config={"recursion_limit": RECURSION_LIMIT}
            )
        except Exception as exc:  # noqa: BLE001 - 与原版一致：失败返回带 error 的输出
            logger.exception("stage=graph_failed")
            return {
                "output": WorkflowOutput(
                    question=question,
                    answer="工作流执行失败。",
                    error=str(exc),
                ),
                "columns": [],
                "rows": [],
                "stages": [],
            }

        output = final_state.get("output")
        if output is None:
            raise RuntimeError("图执行完成但没有产出 WorkflowOutput")

        execution = final_state.get("execution")
        return {
            "output": output,
            "columns": execution.columns if execution else [],
            "rows": (execution.rows if execution else [])[: settings.max_summary_rows],
            "stages": final_state.get("stages", []),
        }

    async def stream(self, question: str) -> AsyncIterator[dict]:
        """按节点产出事件：stage_start / stage_end / final。

        前端据此渲染执行时间线；final 事件携带最终答案与结果表格。
        """

        question = (question or "").strip()
        if not question:
            yield {
                "type": "final",
                "output": WorkflowOutput(
                    question=question, answer="请输入要查询的问题。"
                ).model_dump(),
                "columns": [],
                "rows": [],
                "stages": [],
            }
            return

        state = initial_state(question, self.max_repair_attempts)
        async for event in self.graph.astream_events(
            state, version="v2", config={"recursion_limit": RECURSION_LIMIT}
        ):
            kind = event.get("event")
            name = event.get("name")

            if kind == "on_chain_start" and name in NODE_LABELS:
                yield {
                    "type": "stage_start",
                    "node": name,
                    "label": NODE_LABELS[name],
                }
            elif kind == "on_chain_end" and name in NODE_LABELS:
                update = event.get("data", {}).get("output") or {}
                yield {
                    "type": "stage_end",
                    "node": name,
                    "label": NODE_LABELS[name],
                    "detail": _event_detail(update),
                }
            elif kind == "on_chain_end" and name == "LangGraph":
                final_state = event.get("data", {}).get("output") or {}
                output = final_state.get("output")
                if output is None:
                    raise RuntimeError("图执行完成但没有产出 WorkflowOutput")
                execution = final_state.get("execution")
                rows = execution.rows if execution else []
                yield {
                    "type": "final",
                    "output": output.model_dump(),
                    "columns": execution.columns if execution else [],
                    "rows": rows[: settings.max_summary_rows],
                    "stages": final_state.get("stages", []),
                }


_graph: SQLAgentGraph | None = None


def get_agent_graph() -> SQLAgentGraph:
    """进程级单例：catalog 只解析一次，图只编译一次。"""

    global _graph
    if _graph is None:
        catalog: SchemaCatalog = get_catalog()
        compiled = build_sql_agent_graph(
            catalog=catalog,
            validator=SQLValidator(catalog.db_path),
            executor=SQLExecutor(catalog.db_path),
        )
        _graph = SQLAgentGraph(compiled)
        logger.info(
            "stage=graph_ready nodes=%d max_repair=%d",
            len(NODE_LABELS),
            _graph.max_repair_attempts,
        )
    return _graph
