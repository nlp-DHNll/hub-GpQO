"""离线演示模式：不需要 API Key，也能在网页里看到完整效果。

它不是「假装回答」——SQL 仍然打到真实的 Chinook 数据库上执行，
只是把「选表 / 生成 SQL / 汇总」换成了内置的几条安全 SQL 和固定文案。
这样评审老师在没有 Key 的环境里也能直接体验前端、表格、执行轨迹和流式进度。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncIterator

# 先导入 .config / .service：确保 paths.py 已把作业一加入 sys.path。
from .config import web_settings
from .service import ChatService

from sql_agent_lg.config import settings as agent_settings
from sql_agent_lg.db import SQLExecutor
from sql_agent_lg.graph import GraphRunResult
from sql_agent_lg.models import WorkflowOutput


@dataclass(frozen=True)
class DemoScenario:
    keywords: tuple[str, ...]
    tables: tuple[str, ...]
    sql: str
    title: str


SCENARIOS: tuple[DemoScenario, ...] = (
    DemoScenario(
        keywords=("专辑", "album", "唱片"),
        tables=("albums",),
        sql="SELECT COUNT(*) AS album_count FROM albums",
        title="统计专辑数量",
    ),
    DemoScenario(
        keywords=("流派", "曲风", "genre"),
        tables=("tracks", "genres"),
        sql=(
            "SELECT g.Name AS genre, COUNT(*) AS track_count "
            "FROM tracks AS t "
            "JOIN genres AS g ON t.GenreId = g.GenreId "
            "GROUP BY g.Name "
            "ORDER BY track_count DESC, g.Name "
            "LIMIT 5"
        ),
        title="统计曲目最多的流派",
    ),
    DemoScenario(
        keywords=("客户", "customer", "消费", "金额"),
        tables=("customers", "invoices"),
        sql=(
            "SELECT c.FirstName || ' ' || c.LastName AS customer, "
            "ROUND(SUM(i.Total), 2) AS total_spent "
            "FROM customers AS c "
            "JOIN invoices AS i ON c.CustomerId = i.CustomerId "
            "GROUP BY c.CustomerId "
            "ORDER BY total_spent DESC "
            "LIMIT 5"
        ),
        title="消费金额最高的客户",
    ),
    DemoScenario(
        keywords=("艺人", "歌手", "artist"),
        tables=("artists",),
        sql="SELECT COUNT(*) AS artist_count FROM artists",
        title="统计艺人数量",
    ),
    DemoScenario(
        keywords=("曲目", "歌曲", "track"),
        tables=("tracks",),
        sql="SELECT COUNT(*) AS track_count FROM tracks",
        title="统计曲目数量",
    ),
)

DEFAULT_SCENARIO = DemoScenario(
    keywords=(),
    tables=("artists",),
    sql="SELECT Name FROM artists ORDER BY Name LIMIT 10",
    title="浏览艺人",
)


class DemoGraphRunner:
    """实现与 ``SQLAgentGraph`` 相同的 ``ainvoke`` / ``astream`` 接口。"""

    def __init__(self) -> None:
        self.executor = SQLExecutor(agent_settings.db_path)

    @staticmethod
    def _pick(question: str) -> DemoScenario:
        lowered = question.lower()
        for scenario in SCENARIOS:
            if any(keyword.lower() in lowered for keyword in scenario.keywords):
                return scenario
        return DEFAULT_SCENARIO

    def _answer(self, scenario: DemoScenario, rows: list[list[str]]) -> tuple[str, list[str]]:
        if not rows:
            return "未查询到符合条件的数据。", []

        if scenario.sql.startswith("SELECT COUNT(*)"):
            value = rows[0][0]
            label = {
                "album_count": "张专辑",
                "artist_count": "位艺人",
                "track_count": "首曲目",
            }.get(scenario.sql.split(" AS ")[-1].split()[0], "条记录")
            return f"演示模式：数据库中共有 {value} {label}。", [f"{scenario.title} = {value}"]

        if "genre" in scenario.sql:
            top = rows[0]
            text = "、".join(f"{row[0]}（{row[1]} 首）" for row in rows)
            return f"演示模式：曲目数量最多的流派是 {top[0]}，前 5 名分别是：{text}。", [
                f"{row[0]} = {row[1]} 首" for row in rows
            ]

        if "total_spent" in scenario.sql:
            text = "、".join(f"{row[0]}（{row[1]}）" for row in rows)
            return f"演示模式：消费金额最高的 5 位客户是：{text}。", [
                f"{row[0]} = {row[1]}" for row in rows
            ]

        return (
            f"演示模式：查询返回 {len(rows)} 行，例如 {rows[0][0]}。",
            [f"row_count = {len(rows)}"],
        )

    @staticmethod
    def _events(scenario: DemoScenario, sql: str, rows: int) -> list[dict]:
        return [
            {
                "node": "select_tables",
                "label": "选择数据表",
                "status": "ok",
                "detail": f"演示模式 · tables={list(scenario.tables)}",
                "elapsed_ms": 8,
            },
            {
                "node": "load_schema",
                "label": "加载表结构",
                "status": "ok",
                "detail": f"{len(scenario.tables)} 张表",
                "elapsed_ms": 5,
            },
            {
                "node": "generate_sql",
                "label": "生成 SQL",
                "status": "ok",
                "detail": sql,
                "elapsed_ms": 10,
                "sql": sql,
            },
            {
                "node": "validate_sql",
                "label": "校验 SQL",
                "status": "ok",
                "detail": "通过（演示模式使用内置安全 SQL）",
                "elapsed_ms": 4,
            },
            {
                "node": "execute_sql",
                "label": "执行查询",
                "status": "ok",
                "detail": f"返回 {rows} 行",
                "elapsed_ms": 12,
                "sql": sql,
            },
            {
                "node": "summarize",
                "label": "汇总答案",
                "status": "ok",
                "detail": "演示模式使用固定文案",
                "elapsed_ms": 3,
            },
            {
                "node": "finalize",
                "label": "完成",
                "status": "ok",
                "detail": f"{rows} 行 · 修复 0 次",
                "elapsed_ms": 1,
            },
        ]

    async def ainvoke(self, question: str) -> GraphRunResult:
        started = time.perf_counter()
        scenario = self._pick(question)
        execution = self.executor.execute(scenario.sql)
        answer, evidence = self._answer(scenario, execution.rows)
        events = self._events(scenario, scenario.sql, execution.row_count)
        output = WorkflowOutput(
            question=question,
            answer=answer,
            sql=scenario.sql,
            tables=list(scenario.tables),
            row_count=execution.row_count,
            truncated=execution.truncated,
            repair_attempts=0,
            evidence=evidence,
            caveats=["当前是离线演示模式：SQL 真实执行，但选表/生成/汇总使用内置逻辑。"],
        )
        return GraphRunResult(
            output=output,
            events=events,
            execution=execution,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    async def astream(self, question: str) -> AsyncIterator[dict]:
        result = await self.ainvoke(question)
        for event in result.events:
            await asyncio.sleep(0.12)  # 让前端的进度条有节奏感
            yield {"type": "stage", "event": event}
        yield {"type": "final", "result": result}


def create_demo_service() -> ChatService:
    """演示模式下的 ChatService：不调用任何真实模型。"""

    return ChatService(
        graph_factory=DemoGraphRunner,
        contextualize=False,
    )


# 让调试时可以直接看到演示 SQL
if __name__ == "__main__":  # pragma: no cover
    runner = DemoGraphRunner()
    print(f"演示数据库：{agent_settings.db_path}")
    print(f"演示场景：{len(SCENARIOS)} 个 + 1 个兜底")
    print(f"Web 配置：{web_settings}")
