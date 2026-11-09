"""作业二后端：把作业一的 LangGraph SQL Agent 服务化（FastAPI + SSE）。

- POST /api/chat：SSE 事件流（sse-starlette），前端实时渲染阶段进度；
- 会话：thread_id 由服务端生成/续用，AsyncSqliteSaver 落盘，重启不丢；
- 复用作业一的 SQLAgentGraph（sys.path 注入 src）。

SSE 事件协议：
  meta          {thread_id}                      本轮会话 id（前端续用）
  progress      {node, stage}                    主图节点流转（真实流式）
  sql           {sql}                            可执行 SQL（executed 后）
  clarification {question}                       需要用户澄清（同 thread 续问）
  result        {WorkflowOutput 全字段}           最终结果
  error         {message}                        异常
  done          {}                               流结束

说明：汇总 Agent 走 with_structured_output（function calling），token 级
流式只能拿到工具参数碎片，无法拼出可读文本；因此后端的真实流式体现在
阶段进度事件，answer 的打字机效果由前端渲染节奏实现（见 frontend）。
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sse_starlette.sse import EventSourceResponse

# 复用作业一的 src（sql_agent 包）；放在导入 sql_agent 之前。
WEEK13_ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT1_SRC = WEEK13_ROOT / "作业一" / "sql-agent-langgraph" / "src"
for candidate in (str(ASSIGNMENT1_SRC),):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from sql_agent.checkpoint import open_checkpointer
from sql_agent.graph import SQLAgentGraph
from sql_agent.models import WorkflowOutput

DATA_DIR = Path(__file__).resolve().parent / "data"
CHECKPOINT_DB = DATA_DIR / "checkpoints.sqlite"


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = None

    @field_validator("question", mode="before")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        return value.strip()


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _sse_events(
    graph: SQLAgentGraph, question: str, thread_id: str | None
) -> AsyncIterator[dict[str, str]]:
    """把 graph.astream(updates) 翻译成 SSE 事件字典流。"""

    async def generate() -> AsyncIterator[dict[str, str]]:
        turn_input, config = await graph.prepare_turn(question, thread_id)
        current_thread = str(config["configurable"]["thread_id"])
        yield {"event": "meta", "data": _dump({"thread_id": current_thread})}

        final: WorkflowOutput | None = None
        failed: str | None = None
        try:
            async for chunk in graph.app.astream(
                turn_input, config=config, stream_mode="updates"
            ):
                if not isinstance(chunk, dict):
                    continue
                for node, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    stage = update.get("stage")
                    yield {
                        "event": "progress",
                        "data": _dump({"node": node, "stage": stage}),
                    }
                    if stage == "clarify":
                        clarification = update.get("final")
                        if clarification is not None:
                            yield {
                                "event": "clarification",
                                "data": _dump(
                                    {"question": clarification.answer}
                                ),
                            }
                    if stage == "executed" and update.get("sql"):
                        yield {"event": "sql", "data": _dump({"sql": update["sql"]})}
                    if update.get("final") is not None:
                        final = update["final"]
        except Exception as exc:  # noqa: BLE001 — SSE 连接内异常以事件形式落地
            failed = str(exc)

        if failed is not None:
            yield {"event": "error", "data": _dump({"message": failed})}
        elif final is not None:
            yield {"event": "result", "data": _dump(final.model_dump())}
        else:
            yield {
                "event": "error",
                "data": _dump({"message": "no final output"}),
            }
        yield {"event": "done", "data": "{}"}

    return generate()


def create_app(graph: SQLAgentGraph | None = None) -> FastAPI:
    """构建 FastAPI 应用；graph=None 时在 lifespan 内自建（AsyncSqliteSaver）。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if graph is not None:
            app.state.graph = graph
        else:
            async with open_checkpointer(CHECKPOINT_DB) as checkpointer:
                app.state.graph = SQLAgentGraph(checkpointer=checkpointer)
                yield
                return
        yield

    app = FastAPI(title="Chinook SQL Agent API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/api/chat")
    async def chat(request: ChatRequest) -> EventSourceResponse:
        return EventSourceResponse(
            _sse_events(app.state.graph, request.question.strip(), request.thread_id)
        )

    @app.get("/api/history")
    async def history(thread_id: str) -> dict:
        """从 checkpoint 还原该会话的全部轮次（history + 当前 final）。"""

        graph: SQLAgentGraph = app.state.graph
        try:
            snapshot = await graph.app.aget_state(graph.make_config(thread_id))
        except Exception:  # noqa: BLE001 — 无 checkpoint 的 thread 返回空
            return {"turns": []}
        values = snapshot.values or {}
        turns = []
        for turn in values.get("history") or []:
            turns.append(turn.model_dump() if hasattr(turn, "model_dump") else turn)
        final = values.get("final")
        if final is not None:
            turns.append(
                {
                    "question": str(values.get("question") or ""),
                    **(final.model_dump() if hasattr(final, "model_dump") else final),
                }
            )
        return {"turns": turns}

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
