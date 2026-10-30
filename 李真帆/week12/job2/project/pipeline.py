"""编排层：用 LCEL 把 5 个 Agent + 2 个确定性节点串成一条可重试的流水线。

链路形状（一次“轮次”）::

    SqlGeneratorAgent
        └─(重复/空 SQL)→ 丢弃，进入下一轮
        └─(正常)→ SqlGuard ─(不通过)→ SqlRepair → SqlGuard → SqlCritic
                     └─(通过)→ SqlCritic
        SqlGuard + SqlCritic 都通过 → SqlExecutor
        否则 → 标记本轮失败，交给 Supervisor 决定下一轮

LCEL 本身只做“顺序 + 条件分支”，没有回环能力，
因此“多轮重试”由本层的 while 循环承担，每一轮内部仍然是一条完整的 LCEL 链。
"""

from typing import Any

from langchain_core.runnables import Runnable, RunnableBranch, RunnableLambda

from .agents import (
    AnalystAgent,
    BaseAgent,
    SqlCriticAgent,
    SqlExecutorAgent,
    SqlGeneratorAgent,
    SqlGuardAgent,
    SqlRepairAgent,
    SchemaAgent,
    build_chat_model,
    oneline,
)
from .config import DB_PATH, MAX_ROUNDS
from .db import DBParser
from .tools import SqlToolkit
from .trace import STATUS_FAIL, STATUS_OK, STATUS_WARN, Trace

# Supervisor 的三种路由结果
ROUTE_DONE = "done"
ROUTE_RETRY = "retry"
ROUTE_GIVE_UP = "give_up"


# ═══════════════════════════════════════════════════════════════════════════════
# 调度 Agent：不生产内容，只决定“下一步走哪”
# ═══════════════════════════════════════════════════════════════════════════════

class SupervisorAgent(BaseAgent):
    """调度 Agent（规则决策）。

    它回答的是三个问题：这一轮成了吗？还能再试吗？失败后是“原地修复”还是“重新生成”？
    刻意用确定性规则而不是 LLM：重试预算必须可预测，否则容易在失败方向上烧钱。
    """

    name = "Supervisor"

    def __init__(self, trace: Trace, max_rounds: int = MAX_ROUNDS) -> None:
        self.trace = trace
        self.max_rounds = max_rounds

    def decide(self, state: dict[str, Any], round_no: int) -> str:
        """返回本轮之后的动作：done / retry / give_up。"""
        if state.get("exec_ok"):
            route, why, status = ROUTE_DONE, "查询成功执行", STATUS_OK
        elif round_no >= self.max_rounds:
            route, why, status = ROUTE_GIVE_UP, f"已达最大轮次 {self.max_rounds}", STATUS_FAIL
        elif state.get("skipped"):
            route, why, status = ROUTE_RETRY, "本轮 SQL 为空或与前轮重复，重新生成", STATUS_WARN
        else:
            route, why, status = ROUTE_RETRY, "本轮校验/执行未通过，进入下一轮", STATUS_WARN

        self.trace.record(self.name, "路由决策", detail=f"{route} | {why}", status=status)
        return route


# ═══════════════════════════════════════════════════════════════════════════════
# 单轮链路构建
# ═══════════════════════════════════════════════════════════════════════════════

class SqlAgentPipeline:
    """多 Agent SQL 查询管线。

    对外只需要两件事：``run(question)`` 拿结果，``trace.render()`` 看轨迹。
    """

    def __init__(self, db_path: str = DB_PATH, echo: bool = True) -> None:
        self.trace = Trace(echo=echo)
        self.parser = DBParser(db_path)
        self.toolkit = SqlToolkit(self.parser)

        model = build_chat_model()              # 普通对话
        json_model = build_chat_model(json_mode=True)  # 要求 JSON 输出的场景

        self.schema_agent = SchemaAgent(json_model, self.parser, self.toolkit, self.trace)
        self.generator = SqlGeneratorAgent(json_model, self.trace)
        self.critic = SqlCriticAgent(json_model, self.trace)
        self.repair = SqlRepairAgent(json_model, self.trace)
        self.guard = SqlGuardAgent(self.parser, self.trace)
        self.executor = SqlExecutorAgent(self.parser, self.trace)
        self.analyst = AnalystAgent(model, self.trace)
        self.supervisor = SupervisorAgent(self.trace)

        # 已尝试过的 SQL：跨轮共享，避免同一句话被反复校验、白烧 API
        self._tried: set[str] = set()
        self._last_sql = ""

        self._round_chain = self._build_round_chain()

    # -------------------- 链路装配 --------------------

    def _build_round_chain(self) -> Runnable:
        """装配“一轮”的 LCEL 链。"""
        guard = self.guard.as_runnable()
        review = self.critic.as_runnable()
        repair = self.repair.as_runnable()
        executor = self.executor.as_runnable()

        # 守卫不通过 → 修复 → 重新守卫 → 审查（修复后仍不过则本轮失败）
        # 若修复没产生任何变化，再校验只会得到同样结论，直接判本轮失败，省掉一轮审查调用
        fix_and_recheck = repair | RunnableBranch(
            (lambda s: not s.get("repaired"), RunnableLambda(self._mark_unrepaired, name="Unrepaired")),
            guard | review,
        )

        # 守卫放行才做语义审查；语法都错的 SQL 没必要花一次审查调用
        verified = guard | RunnableBranch(
            (lambda s: not s.get("guard_ok"), fix_and_recheck),
            review,
        )

        # 守卫与审查都通过才执行，否则原地标记失败，交由 Supervisor 决策
        executed = verified | RunnableBranch(
            (lambda s: s.get("guard_ok") and s.get("critic_ok"), executor),
            RunnableLambda(self._mark_not_executed, name="SkipExecute"),
        )

        # 生成端先做一次去重：空 SQL 或与历史重复，直接跳过本轮剩余环节
        return self.generator.as_runnable() | RunnableBranch(
            (lambda s: not s.get("sql") or s.get("sql") in self._tried,
             RunnableLambda(self._mark_skipped, name="SkipRound")),
            executed,
        )

    # -------------------- 确定性兜底节点 --------------------

    def _mark_skipped(self, state: dict[str, Any]) -> dict[str, Any]:
        """生成了空 SQL 或重复 SQL：本轮直接作废。"""
        reason = "未生成有效 SQL" if not state.get("sql") else "与已尝试过的 SQL 重复"
        self.trace.record(self.generator.name, "去重拦截", detail=reason, status=STATUS_WARN)
        return {**state, "guard_ok": False, "critic_ok": False, "exec_ok": False,
                "skipped": True, "result": "", "exec_error": reason}

    def _mark_unrepaired(self, state: dict[str, Any]) -> dict[str, Any]:
        """修复 Agent 没能改变 SQL：本轮直接判失败，交给下一轮重新生成。"""
        return {**state, "guard_ok": False, "critic_ok": False, "exec_ok": False,
                "exec_error": "修复未产生变化", "result": ""}

    def _mark_not_executed(self, state: dict[str, Any]) -> dict[str, Any]:
        """校验未通过：不执行 SQL，把原因留给 Supervisor。"""
        reason = (state.get("guard_msg") or state.get("critic_issues")
                  or state.get("exec_error") or "本轮未通过校验")
        return {**state, "skipped": False, "exec_ok": False,
                "result": "", "exec_error": str(reason)}

    # -------------------- 主流程 --------------------

    def run(self, question: str) -> dict[str, Any]:
        """执行完整流程，返回最终答案与全部关键中间产物。"""
        self._tried.clear()
        self._last_sql = ""

        print("=" * 78)
        print(f"用户问题：{question}")
        print("=" * 78)
        print("[Agent 执行轨迹]")

        state: dict[str, Any] = {"question": question}

        # SchemaAgent 只跑一次：选表结果在整个重试过程中保持不变
        state = self.schema_agent.as_runnable().invoke(state)

        for round_no in range(1, MAX_ROUNDS + 1):
            self.trace.record(self.supervisor.name, f"第 {round_no} 轮",
                              detail="启动 生成 -> 守卫 -> 审查 -> 执行")
            state = self._round_chain.invoke({**state, "round": round_no})

            # 生成出的原句与修复后的句子都记入历史，避免下一轮重复生成同一句
            for seen in (state.get("gen_sql"), state.get("sql")):
                if seen:
                    self._tried.add(seen)
            if state.get("sql"):
                self._last_sql = state["sql"]

            if self.supervisor.decide(state, round_no) != ROUTE_RETRY:
                break

        # 有结果才值得让 Analyst 解读；否则给出明确的失败说明
        if state.get("exec_ok") and state.get("result"):
            state = self.analyst.as_runnable().invoke(state)
            answer = state.get("answer", "")
        else:
            answer = (f"很抱歉，未能成功执行查询（最后尝试的 SQL："
                      f"{oneline(self._last_sql, 200) or '无'}）。")
            self.trace.record(self.analyst.name, "输出兜底",
                              detail="查询未成功，直接说明失败原因", status=STATUS_FAIL)

        print("\n" + self.trace.render())
        print("\n========== 最终答案 ==========")
        print(answer)

        return {
            "question": question,
            "tables": state.get("tables", []),
            "sql": state.get("sql") or self._last_sql,
            "result": state.get("result", ""),
            "answer": answer,
            "rounds": round_no,
            "trace": self.trace.to_list(),
        }

    def close(self) -> None:
        """释放数据库连接。"""
        self.parser.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 对外主入口
# ═══════════════════════════════════════════════════════════════════════════════

def run_query(question: str, db_path: str = DB_PATH, echo: bool = True) -> dict[str, Any]:
    """主入口：给一个问题，走完多 Agent 流水线并返回结果。"""
    pipeline = SqlAgentPipeline(db_path=db_path, echo=echo)
    try:
        return pipeline.run(question)
    finally:
        pipeline.close()
