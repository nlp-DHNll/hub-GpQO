"""编排层：把 10 个节点装配成 LangGraph 状态图。

图结构（详见 ../job1-架构设计.md）::

    START -> router ─(不相关)-> refuse -> END
              └─(相关)-> schema -> generate ◄──────────────────────┐
                                          │ 正常                    │
                                          ▼                        │
                                        guard ─(失败)-> repair     │
                                          │(通过)        │         │
                                          ▼            │(修复后回guard)
                                        critic          │         │
                                          │(通过)        │         │
                                          ▼              │         │
                                        execute          │         │
                                          │(成功)        │         │
                                          ▼              │         │
                                        analyze -> END   │         │
                                                         │         │
        未通过/失败/空SQL/重复 且 rounds < MAX_ROUNDS ────┘         │
        轮次耗尽 ──────────────────────────────> fallback -> END ──┘

多轮重试完全由“条件边 + 环”表达，不再需要 Python while 循环。
"""

from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from .config import DB_PATH, MAX_ROUNDS
from .db.parser import DBParser
from .nodes.analyze_node import make_analyze_node
from .nodes.critic_node import make_critic_node
from .nodes.execute_node import make_execute_node
from .nodes.fallback_node import make_fallback_node
from .nodes.generate_node import make_generate_node
from .nodes.guard_node import make_guard_node
from .nodes.refuse_node import make_refuse_node
from .nodes.repair_node import make_repair_node
from .nodes.router_node import make_router_node
from .nodes.schema_node import make_schema_node
from .state import GraphState
from .tools.db_toolkit import SqlToolkit
from .utils.llm import build_chat_model
from .utils.trace import Trace


# ═══════════════════════════════════════════════════════════════════════════════
# 条件路由（确定性规则，不调用 LLM）
# ═══════════════════════════════════════════════════════════════════════════════

def _can_repair(state: GraphState) -> bool:
    """本轮是否还有原地修复额度：每轮 1 次，即 repairs < rounds。"""
    return state.get("repairs", 0) < state.get("rounds", 1)


def _can_regenerate(state: GraphState) -> bool:
    """是否还能开启新一轮重新生成。"""
    return state.get("rounds", 0) < MAX_ROUNDS


def route_relevance(state: GraphState) -> str:
    """相关性路由：不相关 -> 拒绝，相关 -> 进入 SQL 流程。"""
    return "schema" if state.get("relevant") else "refuse"


def route_generate(state: GraphState) -> str:
    """生成后的路由：空 / 重复 SQL 视作本轮作废。"""
    if state.get("skipped") or not state.get("sql"):
        return "generate" if _can_regenerate(state) else "fallback"
    return "guard"


def route_guard(state: GraphState) -> str:
    """守卫后的路由：失败先原地修复（每轮 1 次），修复额度用完才重新生成。"""
    if state.get("guard_ok"):
        return "critic"
    if _can_repair(state):
        return "repair"
    return "generate" if _can_regenerate(state) else "fallback"


def route_critic(state: GraphState) -> str:
    """审查后的路由：语义不通过 -> 下一轮重新生成（与 week12 口径一致）。"""
    if state.get("critic_ok"):
        return "execute"
    return "generate" if _can_regenerate(state) else "fallback"


def route_repair(state: GraphState) -> str:
    """修复后的路由：有变化回守卫复检；没变化再校验只会得到同样结论。"""
    if state.get("repaired"):
        return "guard"
    return "generate" if _can_regenerate(state) else "fallback"


def route_execute(state: GraphState) -> str:
    """执行后的路由：成功 -> 解读；失败 -> 下一轮重新生成。"""
    if state.get("exec_ok"):
        return "analyze"
    return "generate" if _can_regenerate(state) else "fallback"


# ═══════════════════════════════════════════════════════════════════════════════
# 图装配
# ═══════════════════════════════════════════════════════════════════════════════

def build_graph(api_key: Optional[str] = None, db_path: str = DB_PATH):
    """构建并编译 SQL 智能体状态图。

    :param api_key: DeepSeek API Key；缺省时依次回退到环境变量 / config.py 占位
    :param db_path: SQLite 数据库路径
    """
    parser = DBParser(db_path)
    toolkit = SqlToolkit(parser)

    llm = build_chat_model(api_key=api_key)                       # 普通对话
    json_llm = build_chat_model(api_key=api_key, json_mode=True)  # 要求 JSON 输出

    graph = StateGraph(GraphState)

    # ---- 节点注册 ----
    graph.add_node("router", make_router_node(json_llm))
    graph.add_node("refuse", make_refuse_node())
    graph.add_node("schema", make_schema_node(json_llm, parser, toolkit))
    graph.add_node("generate", make_generate_node(json_llm))
    graph.add_node("guard", make_guard_node(parser))
    graph.add_node("critic", make_critic_node(json_llm))
    graph.add_node("repair", make_repair_node(json_llm))
    graph.add_node("execute", make_execute_node(parser))
    graph.add_node("analyze", make_analyze_node(llm))
    graph.add_node("fallback", make_fallback_node())

    # ---- 边装配 ----
    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", route_relevance, {"schema": "schema", "refuse": "refuse"})
    graph.add_edge("refuse", END)
    graph.add_edge("schema", "generate")
    graph.add_conditional_edges(
        "generate", route_generate,
        {"guard": "guard", "generate": "generate", "fallback": "fallback"},
    )
    graph.add_conditional_edges(
        "guard", route_guard,
        {"critic": "critic", "repair": "repair", "generate": "generate", "fallback": "fallback"},
    )
    graph.add_conditional_edges(
        "critic", route_critic,
        {"execute": "execute", "generate": "generate", "fallback": "fallback"},
    )
    graph.add_conditional_edges(
        "repair", route_repair,
        {"guard": "guard", "generate": "generate", "fallback": "fallback"},
    )
    graph.add_conditional_edges(
        "execute", route_execute,
        {"analyze": "analyze", "generate": "generate", "fallback": "fallback"},
    )
    graph.add_edge("analyze", END)
    graph.add_edge("fallback", END)

    return graph.compile()


# ═══════════════════════════════════════════════════════════════════════════════
# 对外主入口
# ═══════════════════════════════════════════════════════════════════════════════

def run_agent(question: str, api_key: Optional[str] = None,
              db_path: str = DB_PATH, echo: bool = False) -> dict[str, Any]:
    """执行完整工作流，返回最终答案与全部关键中间产物。

    :param question: 用户问题
    :param api_key: DeepSeek API Key（job2 前端传入用户自填的 Key）
    :param echo: 是否实时打印执行轨迹（CLI 打开，服务端关闭）
    """
    trace = Trace(echo=echo)
    graph = build_graph(api_key=api_key, db_path=db_path)

    initial: dict[str, Any] = {
        "question": question,
        "rounds": 0,       # 累加器种子值
        "repairs": 0,      # 累加器种子值
        "tried_sql": [],
    }
    # recursion_limit 放宽：3 轮内最坏路径约 21 个节点，默认 25 已够，留余量更稳
    state = graph.invoke(
        initial,
        config={"recursion_limit": 60, "configurable": {"trace": trace}},
    )

    if echo:
        print("\n" + trace.render())

    return {
        "question": question,
        "rejected": bool(state.get("rejected")),
        "answer": state.get("answer", ""),
        "tables": state.get("tables") or [],
        "sql": state.get("sql", ""),
        "rounds": state.get("rounds", 0),
        "trace": trace.to_list(),
    }
