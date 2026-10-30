
from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI

DEMO_DIR = Path(__file__).resolve().parent
DEFAULT_DB = DEMO_DIR / "chinook.db"

TABLE_HINTS = {
    "artists": "艺术家或乐队",
    "albums": "专辑，属于某位艺术家",
    "tracks": "曲目，属于专辑，含流派、媒体类型、时长和单价",
    "genres": "音乐流派",
    "media_types": "音频媒体类型",
    "playlists": "播放列表",
    "playlist_track": "播放列表和曲目的多对多关系",
    "customers": "客户，含国家、城市，以及负责该客户的员工",
    "employees": "员工，ReportsTo 指向直属上级",
    "invoices": "发票，含开票日期、账单国家和发票总额",
    "invoice_items": "发票明细，记录购买的曲目、单价和数量",
}

JOIN_GUIDE = """
Chinook 是一家数字音乐商店，表之间的业务关系如下：
- artists 一对多 albums，albums 一对多 tracks
- tracks 多对一 genres，tracks 多对一 media_types
- 购买记录：invoices 一对多 invoice_items，invoice_items 多对一 tracks
- 曲目销售额 = invoice_items.UnitPrice * invoice_items.Quantity，不要用 invoices.Total 代替单曲销售额
- customers 一对多 invoices；customers.SupportRepId 指向 employees.EmployeeId
- employees.ReportsTo 指向另一位员工的 EmployeeId
- playlists 与 tracks 通过 playlist_track 形成多对多
- 艺术家和曲目之间必须经过 albums，tracks 上没有 ArtistId
""".strip()

DEMO_QUESTIONS = [
    "每个国家分别有多少位客户？按客户数从高到低排列。",
    "曲目数量最多的音乐流派是什么？",
    "销售额最高的前 5 位艺术家是谁？请给出销售额。",
]


def resolve_llm_config(
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """优先使用环境变量里的云端模型，否则使用本机 Ollama。"""
    env_key = os.getenv("OPENAI_API_KEY")
    env_base = os.getenv("OPENAI_BASE_URL")
    env_model = os.getenv("SQL_AGENT_MODEL")
    if api_key or env_key:
        return {
            "api_key": api_key or env_key,
            "base_url": base_url or env_base or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": model or env_model or "qwen-plus",
            "extra_body": None,
        }
    return {
        "api_key": "ollama",
        "base_url": base_url or env_base or "http://127.0.0.1:11434/v1",
        "model": model or env_model or "qwen3:0.6b",
        "extra_body": {"think": False, "options": {"num_ctx": 16384}},
    }


def build_chat_model(
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> tuple[ChatOpenAI, dict[str, Any]]:
    config = resolve_llm_config(model=model, api_key=api_key, base_url=base_url)
    kwargs: dict[str, Any] = {}
    if config["extra_body"]:
        kwargs["extra_body"] = config["extra_body"]
    chat = ChatOpenAI(
        model=config["model"],
        api_key=config["api_key"],
        base_url=config["base_url"],
        temperature=0,
        max_tokens=1024,
        **kwargs,
    )
    return chat, config


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _list_user_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [row["name"] for row in rows if not row["name"].lower().startswith("sqlite_")]


def _normalize_sql(sql: str) -> str:
    statement = sql.strip()
    fenced = re.findall(r"```sql\s*(.*?)```", statement, flags=re.I | re.S)
    if not fenced:
        fenced = re.findall(r"```\s*(.*?)```", statement, flags=re.S)
    if fenced:
        statement = fenced[0]
    match = re.search(r"(?is)\b(with|select)\b[\s\S]*", statement)
    if match:
        statement = match.group(0)
    return statement.strip().rstrip(";").strip()


def _is_safe_select(sql: str) -> tuple[bool, str]:
    statement = _normalize_sql(sql)
    if not statement:
        return False, "SQL 为空"
    stripped = re.sub(r"/\*.*?\*/", " ", statement, flags=re.S)
    stripped = re.sub(r"--.*?$", " ", stripped, flags=re.M).strip()
    if ";" in stripped:
        return False, "不允许多条 SQL"
    head = stripped.lstrip("(").lower()
    if not (head.startswith("select") or head.startswith("with")):
        return False, "仅允许 SELECT / WITH 查询"
    if re.search(
        r"\b(insert|update|delete|drop|alter|create|attach|detach|replace|pragma|vacuum|reindex)\b",
        head,
    ):
        return False, "检测到非查询语句"
    return True, statement


def make_tools(db_path: Path) -> list:
    """四个数据库工具。闭包持有数据库路径，避免把路径写死在工具参数里。"""

    @tool
    def sql_db_list_tables() -> str:
        """列出数据库中的业务表。回答问题前必须先调用本工具。"""
        with _connect(db_path) as connection:
            names = _list_user_tables(connection)
        lines = []
        for name in names:
            hint = TABLE_HINTS.get(name, "")
            lines.append(f"- {name}" + (f"：{hint}" if hint else ""))
        return "\n".join(lines)

    @tool
    def sql_db_schema(table_names: str) -> str:
        """查看表结构、外键和最多 3 行样例。

        参数 table_names 是逗号分隔的表名，例如 tracks, genres。
        表名必须来自 sql_db_list_tables。
        """
        with _connect(db_path) as connection:
            valid = set(_list_user_tables(connection))
            blocks = []
            for raw_name in re.split(r"[,，]", table_names):
                name = raw_name.strip().strip("`\"'")
                if not name:
                    continue
                if name not in valid:
                    blocks.append(f"错误：表 {name} 不存在")
                    continue
                schema_row = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (name,),
                ).fetchone()
                parts = [schema_row["sql"] if schema_row and schema_row["sql"] else name]
                quoted = '"' + name.replace('"', '""') + '"'
                try:
                    cursor = connection.execute(f"SELECT * FROM {quoted} LIMIT 3")
                    rows = cursor.fetchall()
                    columns = [item[0] for item in cursor.description]
                    sample = ["样例: " + "\t".join(columns)]
                    sample.extend("\t".join("" if value is None else str(value) for value in row) for row in rows)
                    parts.append("\n".join(sample))
                except sqlite3.Error as exc:
                    parts.append(f"读取样例失败: {exc}")
                blocks.append("\n".join(parts))
        return "\n\n".join(blocks) if blocks else "没有解析出表名"

    @tool
    def sql_db_query_checker(query: str) -> str:
        """执行前检查 SQL。只允许一条 SELECT 或 WITH，并用 EXPLAIN 检查语法。

        通过时返回可执行的 SQL。失败时返回错误，需要改写后再次调用本工具。
        执行 sql_db_query 之前必须先调用本工具。
        """
        safe, payload = _is_safe_select(query)
        if not safe:
            return f"不通过: {payload}"
        try:
            with _connect(db_path) as connection:
                connection.execute("EXPLAIN " + payload)
        except sqlite3.Error as exc:
            return f"不通过: {exc}"
        return "通过。可以执行下面这条 SQL：\n" + payload

    @tool
    def sql_db_query(query: str) -> str:
        """执行一条只读 SQL，返回最多 100 行。

        查询不正确时返回错误信息。收到错误后先查看表结构，改写 SQL，再检查并重试。
        禁止 INSERT、UPDATE、DELETE、DROP 等修改语句。
        """
        safe, payload = _is_safe_select(query)
        if not safe:
            return f"错误: {payload}"
        try:
            with _connect(db_path) as connection:
                cursor = connection.execute(payload)
                columns = [item[0] for item in cursor.description or []]
                rows = cursor.fetchmany(101)
        except sqlite3.Error as exc:
            return f"错误: {exc}"
        if not columns:
            return "查询完成，没有结果列"
        truncated = len(rows) > 100
        visible = rows[:100]
        lines = ["\t".join(columns)]
        for row in visible:
            lines.append("\t".join("" if value is None else str(value) for value in row))
        if not visible:
            lines.append("(空结果)")
        if truncated:
            lines.append("结果较多，仅保留前 100 行。")
        return "\n".join(lines)

    return [sql_db_list_tables, sql_db_schema, sql_db_query_checker, sql_db_query]


def build_system_prompt() -> str:
    return f"""你是一个 SQLite 数据分析助手，负责回答 Chinook 音乐商店的业务问题。
请用中文给出结论，并保留查询结果中的关键数字。不要编造结果里没有的数字。

工作顺序：
1. 先调用 sql_db_list_tables，确认有哪些表。
2. 再调用 sql_db_schema，只查看回答问题需要的表。
3. 写一条 SQLite 的 SELECT 或 WITH。
4. 调用 sql_db_query_checker。不通过就根据错误改写，然后再次检查。
5. 检查通过后再调用 sql_db_query。执行报错同样改写后重试。
6. 根据查询结果回答。回答里说明使用的关键数字，不要只重复 SQL。

写法要求：
- 只查询问题相关的列
- 统计问题写清 GROUP BY，排序问题写清 ORDER BY
- 用户指定了前 N 名时使用 LIMIT N；完整分组统计不要擅自加 LIMIT
- 查看明细而用户没有指定条数时，LIMIT 不超过 20
- GROUP BY 的字段要出现在 SELECT 中
- 列名有歧义时加上表前缀

{JOIN_GUIDE}
"""


def build_sql_agent(
    db_path: str | Path | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
):
    """创建 LangChain SQL Agent。返回编译后的图。"""
    target = DEFAULT_DB if db_path is None else Path(db_path)
    if not target.exists():
        raise FileNotFoundError(f"找不到数据库文件: {target}")
    chat, config = build_chat_model(model=model, api_key=api_key, base_url=base_url)
    print(f"模型: {config['model']} @ {config['base_url']}")
    agent = create_agent(
        chat,
        make_tools(target),
        system_prompt=build_system_prompt(),
    )
    return agent


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
        text = "".join(parts)
    else:
        text = str(content or "")
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def run_question(agent, question: str) -> str:
    """跑一轮问答，并按工具调用顺序打印中间过程。"""
    print("\n========== LangChain SQL Agent ==========")
    print(f"问题: {question}")
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"recursion_limit": 30},
    )
    calls: dict[str, dict] = {}
    answer = ""
    for message in result["messages"]:
        for call in getattr(message, "tool_calls", None) or []:
            call_id = str(call.get("id") or "")
            if call_id:
                calls[call_id] = call
        if message.__class__.__name__ == "ToolMessage":
            call = calls.get(str(getattr(message, "tool_call_id", "")), {})
            name = getattr(message, "name", None) or call.get("name", "tool")
            args = call.get("args") or {}
            preview = args.get("query") or args.get("table_names") or ""
            print(f"\n[工具] {name}")
            if preview:
                print(preview)
            print(_message_text(message))
        elif message.__class__.__name__ == "AIMessage" and not getattr(message, "tool_calls", None):
            answer = _message_text(message)
    print("\n[回答]")
    print(answer)
    return answer


def main() -> None:
    agent = build_sql_agent()
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        for question in DEMO_QUESTIONS:
            run_question(agent, question)
        return
    question = " ".join(sys.argv[1:]).strip() or DEMO_QUESTIONS[0]
    run_question(agent, question)


if __name__ == "__main__":
    main()
