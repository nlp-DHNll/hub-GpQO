"""用 LangGraph 复现 Chinook SQL Agent。

图的节点对应原来的固定阶段，校验失败时沿条件边回到改写：

    START
      -> parse_db -> select_tables -> generate_sql -> validate_sql
                                                       | 通过 -> execute_sql -> summarize -> END
                                                       | 失败且未超重试 -> rewrite_sql -> validate_sql
                                                       | 失败且达到重试上限 -> fail -> END

选表、生成、校验、改写、执行和汇总仍调用 `作业1-sql_agent.py` 里的实现，
这里只把控制流改成 StateGraph。未设置 OPENAI_API_KEY 时使用本机 Ollama。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

DEMO_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "homework_sql_agent", DEMO_DIR / "作业1-sql_agent.py"
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("无法加载 作业1-sql_agent.py")
_sql = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _sql
_SPEC.loader.exec_module(_sql)

DEFAULT_DB = _sql.DEFAULT_DB
DEMO_QUESTIONS = _sql.DEMO_QUESTIONS
SQLAgent = _sql.SQLAgent


class SQLState(TypedDict):
    question: str
    entry: str
    selected_tables: list[str]
    expanded_tables: list[str]
    selection_reason: str
    sql: str
    valid: bool
    error: str
    attempt: int
    attempts: list[dict[str, Any]]
    result_columns: list[str]
    result_rows: list[dict[str, Any]]
    truncated: bool
    summary: str
    stop_after_validate: bool
    catalog_tables: list[str]
    foreign_key_count: int


def blank_state(question: str, **overrides: Any) -> SQLState:
    state: SQLState = {
        "question": question,
        "entry": "parse_db",
        "selected_tables": [],
        "expanded_tables": [],
        "selection_reason": "",
        "sql": "",
        "valid": False,
        "error": "",
        "attempt": 0,
        "attempts": [],
        "result_columns": [],
        "result_rows": [],
        "truncated": False,
        "summary": "",
        "stop_after_validate": False,
        "catalog_tables": [],
        "foreign_key_count": 0,
    }
    state.update(overrides)
    return state


def _plain_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = frame.where(pd.notnull(frame), None).to_dict(orient="records")
    cleaned = []
    for row in records:
        item = {}
        for key, value in row.items():
            if hasattr(value, "item") and not isinstance(value, (str, bytes, dict, list)):
                try:
                    value = value.item()
                except Exception:
                    value = str(value)
            item[str(key)] = value
        cleaned.append(item)
    return cleaned


def _frame_from_state(state: SQLState) -> pd.DataFrame:
    if not state["result_rows"]:
        return pd.DataFrame(columns=state["result_columns"])
    return pd.DataFrame(state["result_rows"], columns=state["result_columns"])


def build_sql_graph(agent: SQLAgent):
    """把 SQL Agent 的七步工作流编译成 LangGraph。"""

    def parse_db(state: SQLState) -> dict[str, Any]:
        print("\n[1] 数据库解析")
        names = list(agent.parser.table_names)
        foreign_key_count = len(agent.parser.foreign_keys)
        print("表:", ", ".join(names))
        print(f"外键: {foreign_key_count} 条")
        return {"catalog_tables": names, "foreign_key_count": foreign_key_count}

    def select_tables(state: SQLState) -> dict[str, Any]:
        print("\n[2] table 选择")
        selection = agent.select_tables(state["question"])
        print("选中:", ", ".join(selection["tables"]))
        print("扩展:", ", ".join(selection["expanded_tables"]))
        print("理由:", selection["reason"])
        return {
            "selected_tables": selection["tables"],
            "expanded_tables": selection["expanded_tables"],
            "selection_reason": selection["reason"],
        }

    def generate_sql(state: SQLState) -> dict[str, Any]:
        print("\n[3] sql 生成")
        sql = agent.generate_sql(state["question"], state["expanded_tables"])
        print(sql)
        return {"sql": sql, "attempt": 0, "attempts": []}

    def validate_sql(state: SQLState) -> dict[str, Any]:
        sql = _sql._add_group_columns_to_select(state["sql"])
        if sql != state["sql"]:
            print("\n[5] sql 改写")
            print("规则改写：把 GROUP BY 字段补进 SELECT")
            print(sql)
        attempt = state["attempt"] + 1
        print(f"\n[4] sql 校验（第 {attempt} 次）")
        valid, message = agent.check_answer_sql(
            state["question"], sql, state["expanded_tables"]
        )
        attempts = list(state["attempts"])
        attempts.append({"sql": sql, "ok": valid, "message": message})
        print("通过" if valid else message)
        if valid:
            print("\n[5] sql 改写")
            print("校验已通过，无需改写")
        return {
            "sql": sql,
            "valid": valid,
            "error": message,
            "attempt": attempt,
            "attempts": attempts,
        }

    def rewrite_sql(state: SQLState) -> dict[str, Any]:
        print("\n[5] sql 改写")
        rewritten = agent.rewrite_sql(
            state["question"], state["sql"], state["error"], state["expanded_tables"]
        )
        print(rewritten)
        if not rewritten:
            return {"error": "模型没有返回可执行的 SQL", "valid": False}
        return {"sql": rewritten}

    def execute_sql(state: SQLState) -> dict[str, Any]:
        print("\n[6] sql 执行")
        frame = agent.execute_sql(state["sql"])
        if frame.empty:
            print("(空结果)")
        else:
            print(frame.to_string(index=False))
        truncated = bool(frame.attrs.get("truncated"))
        if truncated:
            print("结果较多，仅保留前 100 行。")
        return {
            "result_columns": [str(column) for column in frame.columns],
            "result_rows": _plain_records(frame),
            "truncated": truncated,
        }

    def summarize(state: SQLState) -> dict[str, Any]:
        print("\n[7] 结果汇总")
        summary = agent.summarize(
            state["question"], state["sql"], _frame_from_state(state)
        )
        print(summary)
        return {"summary": summary}

    def fail(state: SQLState) -> dict[str, Any]:
        raise RuntimeError(f"SQL 校验失败，已达到重试上限: {state['error']}")

    def route_entry(state: SQLState) -> Literal["parse_db", "validate_sql"]:
        if state["entry"] == "validate_sql":
            return "validate_sql"
        return "parse_db"

    def route_after_validate(
        state: SQLState,
    ) -> Literal["execute_sql", "rewrite_sql", "fail", "end"]:
        if state["valid"]:
            if state["stop_after_validate"]:
                return "end"
            return "execute_sql"
        if state["attempt"] >= agent.max_retry:
            return "fail"
        return "rewrite_sql"

    graph = StateGraph(SQLState)
    graph.add_node("parse_db", parse_db)
    graph.add_node("select_tables", select_tables)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("rewrite_sql", rewrite_sql)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("summarize", summarize)
    graph.add_node("fail", fail)

    graph.add_conditional_edges(
        START,
        route_entry,
        {"parse_db": "parse_db", "validate_sql": "validate_sql"},
    )
    graph.add_edge("parse_db", "select_tables")
    graph.add_edge("select_tables", "generate_sql")
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {
            "execute_sql": "execute_sql",
            "rewrite_sql": "rewrite_sql",
            "fail": "fail",
            "end": END,
        },
    )
    graph.add_edge("rewrite_sql", "validate_sql")
    graph.add_edge("execute_sql", "summarize")
    graph.add_edge("summarize", END)
    graph.add_edge("fail", END)
    return graph.compile()


STEP_TITLES = {
    "parse_db": "数据库解析",
    "select_tables": "选择数据表",
    "generate_sql": "生成 SQL",
    "validate_sql": "校验 SQL",
    "rewrite_sql": "改写 SQL",
    "execute_sql": "执行查询",
    "summarize": "结果汇总",
}


def _step_event(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """只把网页需要的字段推出去。"""
    event: dict[str, Any] = {
        "type": "step",
        "node": name,
        "title": STEP_TITLES.get(name, name),
    }
    if name == "parse_db":
        tables = payload.get("catalog_tables") or []
        event["tables"] = tables
        event["foreign_key_count"] = payload.get("foreign_key_count") or 0
    elif name == "select_tables":
        event["tables"] = payload.get("selected_tables") or []
        event["expanded"] = payload.get("expanded_tables") or []
        event["reason"] = payload.get("selection_reason") or ""
    elif name in {"generate_sql", "rewrite_sql"}:
        event["sql"] = payload.get("sql") or ""
        event["message"] = "" if payload.get("sql") else (payload.get("error") or "")
    elif name == "validate_sql":
        event["ok"] = bool(payload.get("valid"))
        event["attempt"] = payload.get("attempt") or 0
        event["message"] = "通过" if payload.get("valid") else (payload.get("error") or "")
        event["sql"] = payload.get("sql") or ""
    elif name == "execute_sql":
        event["columns"] = payload.get("result_columns") or []
        event["rows"] = payload.get("result_rows") or []
        event["truncated"] = bool(payload.get("truncated"))
    elif name == "summarize":
        event["summary"] = payload.get("summary") or ""
    return event


def iter_question(graph, question: str):
    """按节点产出执行过程，最后给出完整结果。"""
    accumulated = blank_state(question)
    try:
        for update in graph.stream(
            blank_state(question),
            stream_mode="updates",
            config={"recursion_limit": 40},
        ):
            if not isinstance(update, dict):
                continue
            for name, payload in update.items():
                if not isinstance(payload, dict):
                    continue
                accumulated.update(payload)
                yield _step_event(name, payload)
        yield {
            "type": "done",
            "question": question,
            "selected_tables": accumulated["selected_tables"],
            "expanded_tables": accumulated["expanded_tables"],
            "selection_reason": accumulated["selection_reason"],
            "sql": accumulated["sql"],
            "attempts": accumulated["attempts"],
            "columns": accumulated["result_columns"],
            "rows": accumulated["result_rows"],
            "truncated": accumulated["truncated"],
            "summary": accumulated["summary"],
        }
    except Exception as exc:
        yield {"type": "error", "message": str(exc)}


def run_question(graph, question: str) -> dict[str, Any]:
    """从数据库解析开始跑完一张图。"""
    print("\n========== LangGraph SQL Agent ==========")
    print(f"问题: {question}")
    result = graph.invoke(blank_state(question), config={"recursion_limit": 40})
    frame = _frame_from_state(result)
    frame.attrs["truncated"] = result["truncated"]
    return {
        "question": question,
        "selected_tables": result["selected_tables"],
        "expanded_tables": result["expanded_tables"],
        "selection_reason": result["selection_reason"],
        "sql": result["sql"],
        "attempts": result["attempts"],
        "frame": frame,
        "summary": result["summary"],
    }


def repair_with_graph(
    graph, question: str, sql: str, table_names: list[str]
) -> dict[str, Any]:
    """从校验节点进入，复现错误 SQL 的改写循环。"""
    return graph.invoke(
        blank_state(
            question,
            entry="validate_sql",
            sql=sql,
            selected_tables=list(table_names),
            expanded_tables=list(table_names),
            stop_after_validate=True,
        ),
        config={"recursion_limit": 40},
    )


def demonstrate_rewrite(graph, agent: SQLAgent) -> None:
    question = "每个国家分别有多少位客户？"
    bad_sql = "SELECT Country, COUNT(*) AS customer_count FROM customer GROUP BY Country"
    print("\n========== SQL 改写演示 ==========")
    print("问题:", question)
    print("错误 SQL:", bad_sql)
    result = repair_with_graph(graph, question, bad_sql, ["customers"])
    print(agent.execute_sql(result["sql"]).head(5).to_string(index=False))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--graph":
        graph = build_sql_graph(SQLAgent(DEFAULT_DB))
        print(graph.get_graph().draw_mermaid())
        return

    agent = SQLAgent(DEFAULT_DB)
    graph = build_sql_graph(agent)
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        demonstrate_rewrite(graph, agent)
        for question in DEMO_QUESTIONS:
            run_question(graph, question)
        return

    question = " ".join(sys.argv[1:]).strip() or DEMO_QUESTIONS[0]
    run_question(graph, question)


if __name__ == "__main__":
    main()
