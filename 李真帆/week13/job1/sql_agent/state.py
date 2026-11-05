"""LangGraph 图状态定义。

所有节点共享这一份状态：节点返回部分字段的 dict，LangGraph 自动合并。
其中 rounds / repairs 是累加器（Annotated[int, add]）：
节点只需返回 ``{"rounds": 1}``，图引擎会自动在旧值上累加，
这是 LangGraph 官方推荐的循环计数写法。
"""

from operator import add
from typing import Annotated, TypedDict


class GraphState(TypedDict, total=False):
    # ---- 输入 ----
    question: str

    # ---- 业务相关性路由 ----
    relevant: bool
    reason: str

    # ---- 选表上下文 ----
    tables: list[str]
    schema: str
    relations: str

    # ---- SQL 生成与校验 ----
    sql: str
    gen_sql: str
    skipped: bool                 # 本轮 SQL 为空或与历史重复
    guard_ok: bool
    guard_msg: str
    critic_ok: bool
    critic_issues: str
    repaired: bool                # 修复是否产生了新 SQL

    # ---- 执行 ----
    exec_ok: bool
    exec_error: str
    result: str
    row_count: int

    # ---- 循环控制 ----
    rounds: Annotated[int, add]   # 生成轮次（generate_node 每次 +1）
    repairs: Annotated[int, add]  # 累计修复次数（repair_node 每次 +1）
    tried_sql: list[str]          # 已尝试过的 SQL（节点内整体更新，用于去重）

    # ---- 输出 ----
    answer: str
    rejected: bool
