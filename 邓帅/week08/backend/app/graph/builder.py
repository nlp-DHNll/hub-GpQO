"""StateGraph 组装:plan→search→read→reflect 条件回边 + 硬上限 + SqliteSaver。"""
from contextlib import asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from app.config import WEEK08_DIR, settings
from app.graph.nodes import (
    plan_node,
    read_node,
    reflect_node,
    search_node,
    synthesize_node,
)
from app.graph.state import ResearchState

CHECKPOINT_DB = WEEK08_DIR / "reports" / "checkpoints.db"


def route_after_reflect(state: ResearchState) -> str:
    """迭代终止条件(任一满足即收敛进 synthesize)。"""
    if state.get("sufficient"):
        return "synthesize"
    if len(state.get("rounds", [])) >= settings.max_rounds:
        return "synthesize"
    if state.get("search_count", 0) >= settings.search_budget:
        return "synthesize"
    if not state.get("pending_queries"):
        return "synthesize"
    return "search"


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(ResearchState)
    g.add_node("plan", plan_node)
    g.add_node("search", search_node)
    g.add_node("read", read_node)
    g.add_node("reflect", reflect_node)
    g.add_node("synthesize", synthesize_node)

    g.add_edge(START, "plan")
    g.add_edge("plan", "search")
    g.add_edge("search", "read")
    g.add_edge("read", "reflect")
    g.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {"search": "search", "synthesize": "synthesize"},
    )
    g.add_edge("synthesize", END)
    return g.compile(checkpointer=checkpointer)


@asynccontextmanager
async def open_checkpointer():
    """进程级 SQLite checkpoint(每 super-step 落盘,支持断点续跑)。"""
    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as saver:
        yield saver
