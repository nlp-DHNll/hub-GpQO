"""使用 LangGraph StateGraph 编排 SQL Agent。"""

from __future__ import annotations

import logging
import time
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from . import workflow as stages
from .models import (
    ExecutionResult,
    FinalAnswer,
    SQLAttempt,
    TableSelection,
    ValidationResult,
    WorkflowOutput,
)

logger = logging.getLogger(__name__)


class SQLAgentState(TypedDict, total=False):
    """LangGraph 节点之间传递的一次查询状态。"""

    question: str
    selection: TableSelection
    schema_context: str
    sql: str
    attempts: list[SQLAttempt]
    validation: ValidationResult
    execution: ExecutionResult
    answer: FinalAnswer
    repair_attempts: int
    cannot_fix: bool
    output: WorkflowOutput


class SQLAgentWorkflow(stages.SQLAgentWorkflow):
    """使用 StateGraph 控制分支与 SQL 修复循环，模型与数据库组件沿用原实现。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        builder = StateGraph(SQLAgentState)
        builder.add_node("select_tables", self._select_tables_node)
        builder.add_node("generate_sql", self._generate_sql_node)
        builder.add_node("validate_sql", self._validate_sql_node)
        builder.add_node("execute_sql", self._execute_sql_node)
        builder.add_node("rewrite_sql", self._rewrite_sql_node)
        builder.add_node("summarize", self._summarize_node)
        builder.add_node("clarify", self._clarify_node)
        builder.add_node("finish_error", self._finish_error_node)

        builder.add_edge(START, "select_tables")
        builder.add_conditional_edges(
            "select_tables",
            self._route_after_selection,
            {"clarify": "clarify", "generate": "generate_sql"},
        )
        builder.add_edge("generate_sql", "validate_sql")
        builder.add_conditional_edges(
            "validate_sql",
            self._route_after_validation,
            {"execute": "execute_sql", "rewrite": "rewrite_sql", "finish": "finish_error"},
        )
        builder.add_conditional_edges(
            "execute_sql",
            self._route_after_execution,
            {"summarize": "summarize", "rewrite": "rewrite_sql", "finish": "finish_error"},
        )
        builder.add_conditional_edges(
            "rewrite_sql",
            self._route_after_rewrite,
            {"validate": "validate_sql", "finish": "finish_error"},
        )
        builder.add_edge("summarize", END)
        builder.add_edge("clarify", END)
        builder.add_edge("finish_error", END)
        self.graph = builder.compile()

    async def run(self, question: str) -> WorkflowOutput:
        """运行状态图并保留 CLI 需要的稳定错误输出。"""

        if not isinstance(question, str):
            raise TypeError("question 必须是字符串")
        question = question.strip()
        if not question:
            return WorkflowOutput(question=question, answer="请输入要查询的问题。")

        started = time.perf_counter()
        logger.info("LangGraph workflow started question=%s", question[:300])
        try:
            state = await self.graph.ainvoke(
                {"question": question, "attempts": [], "repair_attempts": 0}
            )
            output = state.get("output")
            if not isinstance(output, WorkflowOutput):
                raise TypeError("LangGraph 未生成 WorkflowOutput")
            logger.info(
                "LangGraph workflow finished elapsed=%.2fs tables=%s rows=%d repairs=%d",
                time.perf_counter() - started,
                output.tables,
                output.row_count,
                output.repair_attempts,
            )
            return output
        except Exception as exc:  # noqa: BLE001 - CLI 需要稳定输出
            logger.exception("LangGraph SQL agent workflow failed")
            return WorkflowOutput(
                question=question,
                answer=f"处理失败：{exc}",
                error=str(exc),
            )

    async def _select_tables_node(self, state: SQLAgentState) -> dict:
        selection = await self._select_tables(state["question"])
        update: dict = {"selection": selection}
        if not selection.needs_clarification and selection.tables:
            update["schema_context"] = self.catalog.render_schema(selection.tables)
        return update

    def _route_after_selection(self, state: SQLAgentState) -> Literal["clarify", "generate"]:
        selection = state["selection"]
        if selection.needs_clarification or not selection.tables:
            return "clarify"
        return "generate"

    async def _generate_sql_node(self, state: SQLAgentState) -> dict:
        draft = await self._generate_sql(state["question"], state["schema_context"])
        return {
            "sql": draft.sql,
            "attempts": [*state.get("attempts", []), SQLAttempt(sql=draft.sql, source="generator")],
        }

    def _validate_sql_node(self, state: SQLAgentState) -> dict:
        validation = self.validator.validate(state["sql"])
        attempts = list(state.get("attempts", []))
        if not validation.ok and attempts:
            attempts[-1] = attempts[-1].model_copy(
                update={"code": validation.code, "error": validation.message}
            )
        return {"validation": validation, "attempts": attempts}

    def _route_after_validation(
        self, state: SQLAgentState
    ) -> Literal["execute", "rewrite", "finish"]:
        if state["validation"].ok:
            return "execute"
        return self._repair_or_finish(state)

    def _execute_sql_node(self, state: SQLAgentState) -> dict:
        try:
            execution = self.executor.execute(state["validation"].normalized_sql)
            return {"execution": execution, "sql": state["validation"].normalized_sql}
        except stages.SQLExecutionError as exc:
            validation = ValidationResult(
                ok=False,
                code=exc.code,
                message=str(exc),
                normalized_sql=state["sql"],
            )
            attempts = list(state.get("attempts", []))
            if attempts:
                attempts[-1] = attempts[-1].model_copy(
                    update={"code": validation.code, "error": validation.message}
                )
            return {"validation": validation, "attempts": attempts}

    def _route_after_execution(
        self, state: SQLAgentState
    ) -> Literal["summarize", "rewrite", "finish"]:
        if "execution" in state:
            return "summarize"
        return self._repair_or_finish(state)

    def _repair_or_finish(self, state: SQLAgentState) -> Literal["rewrite", "finish"]:
        if state.get("repair_attempts", 0) >= self.max_repair_attempts:
            return "finish"
        return "rewrite"

    async def _rewrite_sql_node(self, state: SQLAgentState) -> dict:
        attempt_number = state.get("repair_attempts", 0) + 1
        draft = await self._rewrite_sql(
            question=state["question"],
            schema=state["schema_context"],
            sql=state["sql"],
            validation=state["validation"],
            attempts=state.get("attempts", []),
            attempt_number=attempt_number,
        )
        if draft.cannot_fix:
            return {"cannot_fix": True, "answer": FinalAnswer(answer=draft.explanation)}
        return {
            "sql": draft.sql,
            "repair_attempts": attempt_number,
            "attempts": [
                *state.get("attempts", []),
                SQLAttempt(sql=draft.sql, source="rewriter"),
            ],
            "cannot_fix": False,
        }

    def _route_after_rewrite(self, state: SQLAgentState) -> Literal["validate", "finish"]:
        return "finish" if state.get("cannot_fix") else "validate"

    async def _summarize_node(self, state: SQLAgentState) -> dict:
        execution = state["execution"]
        if execution.row_count == 0:
            answer = FinalAnswer(
                answer="未查询到符合条件的数据。",
                caveats=["SQL 执行成功，但结果集为空。"],
            )
        else:
            answer = await self._summarize(state["question"], state["sql"], execution)
        selection = state["selection"]
        return {
            "answer": answer,
            "output": WorkflowOutput(
                question=state["question"],
                answer=answer.answer,
                sql=state["sql"],
                tables=selection.tables,
                row_count=execution.row_count,
                truncated=execution.truncated,
                repair_attempts=state.get("repair_attempts", 0),
                evidence=answer.evidence,
                caveats=answer.caveats,
            ),
        }

    def _clarify_node(self, state: SQLAgentState) -> dict:
        selection = state["selection"]
        return {
            "output": WorkflowOutput(
                question=state["question"],
                answer=selection.clarification_question
                or "无法从当前数据库确定回答该问题所需的表。",
                tables=selection.tables,
            )
        }

    def _finish_error_node(self, state: SQLAgentState) -> dict:
        selection = state.get("selection")
        validation = state.get("validation")
        if state.get("cannot_fix"):
            answer = f"当前数据库无法回答该问题：{state['answer'].answer}"
        else:
            answer = "无法生成可执行的 SQL，已达到最大修复次数。"
        return {
            "output": WorkflowOutput(
                question=state["question"],
                answer=answer,
                sql=state.get("sql"),
                tables=selection.tables if selection else [],
                repair_attempts=state.get("repair_attempts", 0),
                error=validation.message if validation else None,
            )
        }
