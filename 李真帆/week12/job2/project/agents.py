"""五个专职 Agent（全部用 LCEL 链表达）。

分工：
    SchemaAgent        —— 决定“看哪些表”，装配 schema 与外键上下文
    SqlGeneratorAgent  —— 把问题翻译成 SQL（首轮创作）
    SqlCriticAgent     —— 语义审查，只挑错不改写
    SqlRepairAgent     —— 拿着错误信息改写 SQL
    AnalystAgent       —— 把结果讲成业务结论

另外两个确定性节点（不调用 LLM，保证执行安全与可复现）：
    SqlGuardAgent      —— 只读静态校验 + EXPLAIN 试跑
    SqlExecutorAgent   —— 真正执行并取回结果

每个 Agent 都暴露一个 Runnable（``as_runnable()``），由 pipeline.py 用 LCEL 串起来。
"""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_openai import ChatOpenAI

from . import prompts
from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    LLM_MAX_RETRIES,
    TEMPERATURE,
)
from .db import DBParser
from .parsing import as_bool, normalize_tables, parse_json, pick_sql
from .tools import SqlToolkit, to_markdown
from .trace import STATUS_FAIL, STATUS_OK, STATUS_WARN, Trace


def build_chat_model(json_mode: bool = False) -> Runnable:
    """构建 DeepSeek 聊天模型。

    DeepSeek 兼容 OpenAI 协议，因此直接用 langchain-openai 的 ChatOpenAI；
    json_mode 走 DeepSeek 支持的 ``response_format={"type": "json_object"}``，
    不要用 json_schema（DeepSeek 不支持，会直接报 400）。
    """
    key = (DEEPSEEK_API_KEY or "").strip()
    if not key or key == "your_api_key":
        raise RuntimeError(
            "未配置 DEEPSEEK_API_KEY：请设置同名环境变量，"
            "或在 project/config.py 的 DEEPSEEK_API_KEY 处填写"
        )

    model = ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=key,
        base_url=DEEPSEEK_BASE_URL,
        temperature=TEMPERATURE,
        max_retries=LLM_MAX_RETRIES,
        timeout=60,
    )
    return model.bind(response_format={"type": "json_object"}) if json_mode else model


def oneline(text: str, limit: int = 80) -> str:
    """把多行内容压成一行，避免轨迹表被换行打乱。"""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "..."


class BaseAgent:
    """Agent 基类：统一提供 Runnable 入口与名称。"""

    name = "BaseAgent"

    def as_runnable(self) -> Runnable:
        """把 Agent 包装成可被 LCEL 组合的 Runnable。"""
        return RunnableLambda(self._step, name=self.name)

    def _step(self, state: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - 由子类实现
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 1：SchemaAgent
# ═══════════════════════════════════════════════════════════════════════════════

class SchemaAgent(BaseAgent):
    """选表 Agent：从全库中挑出回答问题所需的最小表集合，并装配上下文。

    它的输入是“表清单 + 工具清单”，输出是 schema 文本与外键关系，
    后续 SqlGenerator / SqlCritic / SqlRepair 都复用这份上下文。
    """

    name = "SchemaAgent"

    def __init__(self, model: BaseChatModel, parser: DBParser,
                 toolkit: SqlToolkit, trace: Trace) -> None:
        self.parser = parser
        self.toolkit = toolkit
        self.trace = trace
        # LCEL 链：提示词 -> 模型 -> 文本
        self.chain: Runnable = (
            ChatPromptTemplate.from_messages([
                ("system", prompts.SCHEMA_SYSTEM),
                ("human", prompts.SCHEMA_HUMAN),
            ])
            | model
            | StrOutputParser()
        )

    def _step(self, state: dict[str, Any]) -> dict[str, Any]:
        question = state["question"]
        tables: list[str] = []
        reason = ""
        with self.trace.span(self.name, "选表") as box:
            raw = self.chain.invoke({
                "tool_list": self.toolkit.describe(),
                "all_tables": self.parser.describe_all_tables(),
                "question": question,
            })
            data = parse_json(raw)
            tables = normalize_tables(data.get("tables"), self.parser.table_names)
            reason = str(data.get("reason") or "")

            if tables:
                box["status"] = STATUS_OK
                box["detail"] = f"{tables} | {oneline(reason, 50)}"
            else:
                # 兜底：选不出表时退化为前几张表，不让整条链断掉
                tables = self.parser.table_names[:5]
                box["status"] = STATUS_WARN
                box["detail"] = f"未得到有效表名，回退为 {tables}"

        schema = "\n\n".join(self.parser.describe_table(t) for t in tables)
        relations = self.parser.describe_relations(tables)
        return {**state, "tables": tables, "reason": reason,
                "schema": schema, "relations": relations}


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 2：SqlGeneratorAgent
# ═══════════════════════════════════════════════════════════════════════════════

class SqlGeneratorAgent(BaseAgent):
    """SQL 创作 Agent：基于 schema 与外键，把问题翻译成一条只读查询。"""

    name = "SqlGeneratorAgent"

    def __init__(self, model: BaseChatModel, trace: Trace) -> None:
        self.trace = trace
        self.chain: Runnable = (
            ChatPromptTemplate.from_messages([
                ("system", prompts.SQL_GEN_SYSTEM),
                ("human", prompts.SQL_GEN_HUMAN),
            ])
            | model
            | StrOutputParser()
        )

    def _step(self, state: dict[str, Any]) -> dict[str, Any]:
        with self.trace.span(self.name, "生成 SQL") as box:
            raw = self.chain.invoke({
                "schema": state["schema"],
                "relations": state["relations"],
                "question": state["question"],
            })
            sql = pick_sql(parse_json(raw), raw)
            if sql:
                box["status"] = STATUS_OK
                box["detail"] = oneline(sql)
            else:
                box["status"] = STATUS_FAIL
                box["detail"] = "模型未返回有效 SQL"
        return {**state, "sql": sql, "gen_sql": sql, "repaired": False}


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 3：SqlCriticAgent
# ═══════════════════════════════════════════════════════════════════════════════

class SqlCriticAgent(BaseAgent):
    """审查 Agent：只看语义是否正确，不产出改写后的 SQL。

    与生成 Agent 分离，是为了避免“自己写、自己批”带来的自我肯定偏差。
    """

    name = "SqlCriticAgent"

    def __init__(self, model: BaseChatModel, trace: Trace) -> None:
        self.trace = trace
        self.chain: Runnable = (
            ChatPromptTemplate.from_messages([
                ("system", prompts.SQL_CRITIC_SYSTEM),
                ("human", prompts.SQL_CRITIC_HUMAN),
            ])
            | model
            | StrOutputParser()
        )

    def _step(self, state: dict[str, Any]) -> dict[str, Any]:
        ok, issues = True, ""
        with self.trace.span(self.name, "语义审查") as box:
            raw = self.chain.invoke({
                "schema": state["schema"],
                "relations": state["relations"],
                "question": state["question"],
                "sql": state["sql"],
            })
            data = parse_json(raw)
            if not data:
                # 审查结果不可解析时默认放行，避免流程死循环，但明确标注
                box["status"] = STATUS_WARN
                box["detail"] = "审查结果不可解析，默认放行"
            else:
                ok = as_bool(data.get("valid"), default=True)
                issues = str(data.get("issues") or "")
                if ok:
                    box["status"] = STATUS_OK
                    box["detail"] = "语义通过"
                else:
                    box["status"] = STATUS_FAIL
                    box["detail"] = oneline(issues)
        return {**state, "critic_ok": ok, "critic_issues": issues}


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 4：SqlRepairAgent
# ═══════════════════════════════════════════════════════════════════════════════

class SqlRepairAgent(BaseAgent):
    """修复 Agent：把错误信息（校验失败 / 数据库报错）回灌后改写出新 SQL。"""

    name = "SqlRepairAgent"

    def __init__(self, model: BaseChatModel, trace: Trace) -> None:
        self.trace = trace
        self.chain: Runnable = (
            ChatPromptTemplate.from_messages([
                ("system", prompts.SQL_REPAIR_SYSTEM),
                ("human", prompts.SQL_REPAIR_HUMAN),
            ])
            | model
            | StrOutputParser()
        )

    def _step(self, state: dict[str, Any]) -> dict[str, Any]:
        old_sql = state["sql"]
        # 错误来源按“谁拦下的”来取：守卫拦的就给语法/只读原因，
        # 审查或执行拦的就给语义原因，避免把上一轮的旧问题喂给模型
        if not state.get("guard_ok", True):
            error = state.get("guard_msg") or "未通过只读校验"
        else:
            error = state.get("critic_issues") or state.get("exec_error") or "未知问题"
        new_sql = old_sql
        with self.trace.span(self.name, "修复 SQL") as box:
            raw = self.chain.invoke({
                "schema": state["schema"],
                "relations": state["relations"],
                "question": state["question"],
                "sql": old_sql,
                "error": error,
            })
            new_sql = pick_sql(parse_json(raw), raw) or old_sql
            if new_sql == old_sql:
                # 修复没产生变化，再校验一次只会得到同样结果，交给下一轮重新生成
                box["status"] = STATUS_WARN
                box["detail"] = "修复未产生变化，转入下一轮重新生成"
            else:
                box["status"] = STATUS_OK
                box["detail"] = oneline(new_sql)
        return {**state, "sql": new_sql, "repaired": new_sql != old_sql}


# ═══════════════════════════════════════════════════════════════════════════════
# 确定性节点 1：SqlGuardAgent（执行前守卫，不调用 LLM）
# ═══════════════════════════════════════════════════════════════════════════════

class SqlGuardAgent(BaseAgent):
    """守卫节点：静态只读检查 + EXPLAIN 试跑。

    这一步刻意不用 LLM——能不能执行必须由确定性规则说了算。
    """

    name = "SqlGuard"

    def __init__(self, parser: DBParser, trace: Trace) -> None:
        self.parser = parser
        self.trace = trace

    def _step(self, state: dict[str, Any]) -> dict[str, Any]:
        sql = state.get("sql") or ""
        ok, msg = self.parser.check_sql(sql) if sql else (False, "SQL 为空")
        with self.trace.span(self.name, "只读守卫") as box:
            box["status"] = STATUS_OK if ok else STATUS_FAIL
            box["detail"] = "通过" if ok else oneline(msg)
        return {**state, "guard_ok": ok, "guard_msg": msg}


# ═══════════════════════════════════════════════════════════════════════════════
# 确定性节点 2：SqlExecutorAgent（真正执行，不调用 LLM）
# ═══════════════════════════════════════════════════════════════════════════════

class SqlExecutorAgent(BaseAgent):
    """执行节点：在只读连接上跑 SQL，并把结果渲染成表格文本。"""

    name = "SqlExecutor"

    def __init__(self, parser: DBParser, trace: Trace) -> None:
        self.parser = parser
        self.trace = trace

    def _step(self, state: dict[str, Any]) -> dict[str, Any]:
        rows_count = 0
        with self.trace.span(self.name, "执行 SQL") as box:
            ok, msg, cols, rows = self.parser.execute_sql(state["sql"])
            if ok:
                result = to_markdown(cols, rows) if cols else "（无结果集）"
                rows_count = len(rows)
                box["status"] = STATUS_OK
                box["detail"] = f"取回 {rows_count} 行"
            else:
                result = ""
                box["status"] = STATUS_FAIL
                box["detail"] = oneline(msg)
        return {**state, "exec_ok": ok, "exec_error": "" if ok else msg,
                "result": result, "row_count": rows_count}


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 5：AnalystAgent
# ═══════════════════════════════════════════════════════════════════════════════

class AnalystAgent(BaseAgent):
    """解读 Agent：把查询结果翻译成业务能直接用的结论。"""

    name = "AnalystAgent"

    def __init__(self, model: BaseChatModel, trace: Trace) -> None:
        self.trace = trace
        self.chain: Runnable = (
            ChatPromptTemplate.from_messages([
                ("system", prompts.ANALYST_SYSTEM),
                ("human", prompts.ANALYST_HUMAN),
            ])
            | model
            | StrOutputParser()
        )

    def _step(self, state: dict[str, Any]) -> dict[str, Any]:
        with self.trace.span(self.name, "解读结果") as box:
            answer = self.chain.invoke({
                "question": state["question"],
                "sql": state["sql"],
                "result": state["result"],
            }).strip()
            box["status"] = STATUS_OK
            box["detail"] = oneline(answer, 60)
        return {**state, "answer": answer}
