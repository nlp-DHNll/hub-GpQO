SQL Agent 设计文档：基于 LangGraph 的 Agent 划分与编排
版本：v1.0
范围：基于 ref/chinook.db 的单库、单轮自然语言查询
行为参考：ref/sql-agent.ipynb（仅作为行为参考，代码需重新组织）
编排框架：LangGraph StateGraph

0. 文档约定
本文档同时引用两个 ref/ 下的文件，角色不同，不得混淆：

文件	角色	使用方式
ref/chinook.db	素材/被测数据库	只读连接，作为 SchemaCatalog 的解析对象和 SQLExecutor 的执行目标
ref/sql-agent.ipynb	行为参考	只参考其“选表→生成→校验→执行→汇总”的流程意图；不 import 其代码

notebook 中有三处必须修复或不得复用，全文会反复引用：

DBParser.check_sql() 用 engine.begin() 真执行 SQL，不是 dry-run。不得复用，替换为 EXPLAIN 编译校验。

DBParser.get_table_sample() 只取 fetchone() 单行。必须修复为 3 行样例。

金标生成循环用 parser.table_names[:1] 且处理完第一张表就 break。必须修复为遍历全部业务表并按 query_type 矩阵组织。

1. 目标与非目标
1.1 目标
实现一条完整、可观测、可控的 SQL Agent 工作流：

数据库解析 → 表选择 → SQL 生成 → SQL 校验 → SQL 改写 → SQL 执行 → 结果汇总

核心设计问题不是“用几个 Agent”，而是哪些步骤应该交给 LLM，哪些必须由确定性代码控制。本文档给出基于 LangGraph 的组件划分、状态契约、图结构、节点职责、失败处理策略和可观测性方案。

1.2 非目标（v1）
多轮对话、上下文追问（澄清走终止返回，不引入 interrupt）

多数据库/多方言动态切换

写操作（INSERT/UPDATE/DELETE/DDL）

完全自主的 Agent 规划（autonomous planning）

FastAPI 服务（v1 入口为 CLI，v2 再考虑）

2. 划分原则
LLM 只做语义判断：选表、写 SQL、根据错误修复 SQL、把结果转成自然语言。

校验和执行必须是确定性代码：LLM 不能“批准”自己生成的 SQL，也不能直接持有数据库写权限。

一个 Agent 只做一个决策：避免一个超长 prompt 同时负责选表、生成、纠错和总结，否则无法定位错误、无法单独重试。

上下文最小化：选表阶段只看目录摘要；生成/改写阶段只看已选表的详细 schema，降低 token 和幻觉。

主流程由确定性条件边控制：分支、循环、重试预算和最终答案组装由 LangGraph 的条件边和确定性节点负责，不交给 LLM 自主决定下一步。table_select 子循环内部允许消息驱动的工具调用，但子循环的退出条件由图的条件边判断，不由模型决定。

失败有界：所有 LLM 修复循环都有次数上限，超限返回明确错误，不无限重试。

依赖方向单向：确定性组件不依赖 LLM 组件，节点不依赖图装配，路由函数不依赖节点。

3. 组件总览
3.1 组件表
组件	类型	职责	是否 LLM	模型
StateGraph 编译产物	框架	节点调度、条件边路由、状态归并	否	—
SchemaCatalog	确定性代码	解析 DB、缓存 schema/统计/外键/样例、两种渲染视图、连通性判断	否	—
TableSelectAgent	Agent（节点内 LLM）	从表清单中选择回答所需的最少表集合，可调用 get_table_schema 工具	是	deepseek-flash
SQLGeneratorAgent	Agent（节点内 LLM）	基于问题 + 已选表 schema 生成 SQLite SQL	是	deepseek-flash
SQLValidator	确定性代码	安全门禁、EXPLAIN 编译校验、错误码映射	否	—
SQLRewriteAgent	Agent（节点内 LLM）	根据校验或执行错误修复 SQL，支持 cannot_fix	是	deepseek-flash
SQLExecutor	确定性代码	只读执行、超时、行数/单元格截断	否	—
ResultSummaryAgent	Agent（节点内 LLM）	将问题、SQL、结果汇总为自然语言答案	是	deepseek-flash
observability	确定性代码	消费 astream(updates)、结构化日志、token 回调	否	—

3.2 LangGraph 流程图

flowchart TD
    START([START]) --> TS[table_select]
    TS --> route_select{route_after_select}
    route_select -- tool_calls --> TST[table_select_tools]
    TST --> TS
    route_select -- 无 tool_calls --> VS[validate_selection]
    VS --> route_vs{route_after_validate_selection}
    route_vs -- 非法且预算未耗尽 --> TS
    route_vs -- 合法 --> SR[schema_render]
    route_vs -- 需澄清/预算耗尽 --> CR[clarify_or_reject]
    SR --> SG[sql_generate]
    SG --> VSQL[validate_sql]
    VSQL --> route_vsql{route_after_validate_sql}
    route_vsql -- ok --> EX[execute]
    route_vsql -- 失败且未超预算且非cannot_fix --> RW[sql_rewrite]
    route_vsql -- 超预算或cannot_fix --> FA[failure_answer]
    RW --> VSQL
    EX --> route_ex{route_after_execute}
    route_ex -- 成功 --> SUM[summarize]
    route_ex -- 失败且未超预算且非cannot_fix --> RW
    route_ex -- 超预算或cannot_fix --> FA
    SUM --> END([END])
    CR --> END
    FA --> END

图的三个关键特征：

table_select 与 table_select_tools 构成消息驱动的工具子循环，退出条件在 route_after_select 判断“最后一条消息有无 tool_calls”。

sql_rewrite 的出口固定回 validate_sql，不直接去 execute——改写后必须重新校验。

cannot_fix 在两个条件边中短路到 failure_answer，不继续消耗预算。

4. 数据契约
4.1 State 定义（state.py）
import operator
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage
from .models import (
    TableSelection, SQLAttempt, ValidationResult,
    ExecutionResult, FinalAnswer,
)

class SQLAgentState(TypedDict, total=False):
    # 输入
    question: str

    # 选表子循环（路径 B：消息驱动工具调用）
    selection_messages: Annotated[list[AnyMessage], add_messages]
    selection: TableSelection | None
    selection_retry_count: int            # 独立预算，上限 1

    # 生成/修复
    schema_context: str
    sql: str | None
    attempts: Annotated[list[SQLAttempt], operator.add]
    repair_attempts: int                  # 共享预算，上限 3

    # 校验/执行/汇总
    validation: ValidationResult | None
    execution: ExecutionResult | None
    answer: FinalAnswer | None

    # 可观测性（仅日志，不参与路由）
    stage: str
    last_error: str | None

约定：

total=False：图入口只需 {"question": ...}，其余字段由节点逐步填充。

selection_messages 用 add_messages reducer：节点只返回新增消息，LangGraph 按 id 归并。反馈消息用 uuid 生成稳定 id，避免重试时覆盖。

attempts 用 operator.add reducer：节点只返回增量 [本次这一条]。

未标注 reducer 的字段是覆盖写：sql、validation、execution、selection、repair_attempts、selection_retry_count 返回什么就是什么。

两个计数器独立：selection_retry_count 上限 1，不占用 repair_attempts 的 3 次预算。

stage 保留但只写不读：作为日志辅助，条件边一律不看 stage。

MAX_SELECTION_RETRY 和 MAX_REPAIR_ATTEMPTS 常量放 config.py，不放 State。

4.2 Pydantic 模型（models.py）
from enum import Enum
from pydantic import BaseModel, Field, model_validator


class TableSelection(BaseModel):
    tables: list[str] = Field(description="回答该问题所需的最少表名集合")
    reason: str = Field(description="选择这些表的理由")
    confidence: float = Field(ge=0, le=1)
    needs_clarification: bool = False
    clarification_question: str | None = None


class SQLDraft(BaseModel):
    sql: str = ""
    explanation: str = ""
    assumptions: list[str] = Field(default_factory=list)
    cannot_fix: bool = False
    cannot_fix_reason: str | None = None

    @model_validator(mode="after")
    def validate_cannot_fix(self):
        if self.cannot_fix:
            if self.sql:
                raise ValueError("cannot_fix=true 时不应提供 sql")
            if not self.cannot_fix_reason:
                raise ValueError("cannot_fix=true 时必须说明原因")
        elif not self.sql:
            raise ValueError("cannot_fix=false 时必须提供 sql")
        return self


class ErrorCode(str, Enum):
    UNSAFE = "unsafe"                  # 非 SELECT / 多语句 / 危险关键字
    SYNTAX = "syntax"                  # 语法错误
    UNKNOWN_OBJECT = "unknown_object"  # 表或列不存在
    AMBIGUOUS = "ambiguous"            # 列名歧义
    RUNTIME = "runtime"                # 执行期错误
    TIMEOUT = "timeout"
    EMPTY = "empty"                    # 结果为空（不是错误）


class ValidationResult(BaseModel):
    ok: bool
    code: ErrorCode | None = None
    message: str = ""
    normalized_sql: str = ""


class ExecutionResult(BaseModel):
    columns: list[str]
    rows: list[list[str]]              # 已转字符串、已截断
    row_count: int
    truncated: bool = False


class SQLAttempt(BaseModel):
    sql: str
    source: str                        # generator / rewriter
    code: ErrorCode | None = None
    error: str = ""


class FinalAnswer(BaseModel):
    answer: str
    evidence: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)

约定：

表名、列名必须与 catalog 完全一致（Chinook 列名为 PascalCase）。

rows 统一字符串化，避免 Decimal/日期序列化差异。

SQLDraft 扩展 cannot_fix 后，生成 Agent 与改写 Agent 共享同一契约；生成 Agent 的 cannot_fix 恒为 False。

cannot_fix 的互斥关系由 model_validator 在 Pydantic 层强制，StructuredAgent._parse 解析失败时抛异常，由节点层处理。

5. 主流程与状态机
5.1 正常路径
图外：SchemaCatalog.load() 解析 DB，构建目录摘要与详细 schema（进程级单例，按 DB mtime 失效）。

table_select：输入问题 + 目录摘要，LLM 可调用 get_table_schema 工具；工具调用经 table_select_tools 节点返回 ToolMessage。

validate_selection：解析 TableSelection，校验表名合法性与连通性；非法时追加反馈消息并递增 selection_retry_count。

schema_render：调 catalog.render_schema(tables)，纯函数。

sql_generate：输入问题 + 已选表详细 schema + 连接关系 + 3 行样例，输出 SQLDraft。

validate_sql：安全检查 + EXPLAIN 编译校验。

execute：只读执行，限制超时和返回行数。

summarize：输入问题、最终 SQL、列、结果行（前 50 行），输出 FinalAnswer。

5.2 节点清单与契约
节点	类型	读 State	写 State	说明
table_select	LLM + tools	question, selection_messages	selection_messages, stage	首次进入初始化 system + user；重试复用历史
table_select_tools	确定性	最后一条 AIMessage.tool_calls	selection_messages	白名单校验，返回 ToolMessage
validate_selection	确定性	selection_messages, selection_retry_count	selection, selection_retry_count, selection_messages, last_error, stage	解析、校验表名与连通性；非法时递增计数器并追加反馈
schema_render	确定性	selection.tables	schema_context, stage	纯函数
sql_generate	LLM	question, schema_context	sql, attempts, stage	输出 SQLDraft，追加 SQLAttempt(source="generator")
validate_sql	确定性	sql	validation, stage	不递增计数器
sql_rewrite	LLM	question, schema_context, sql, validation, attempts	sql, repair_attempts+1, attempts, last_error, stage	入口递增预算；cannot_fix 时写 last_error 不改 sql
execute	确定性	sql	execution 或 validation（失败时）, last_error, stage	失败时显式 execution=None
summarize	LLM	question, sql, execution	answer, stage	节点内 try/except 降级
clarify_or_reject	终止	selection / last_error	answer, stage	v1 简单路径，不引入 interrupt
failure_answer	终止	validation, attempts, repair_attempts	answer, stage	超预算或 cannot_fix 时终止

5.3 条件边路由函数（routes.py）
MAX_REPAIR_ATTEMPTS = 3
MAX_SELECTION_RETRY = 1

def route_after_select(state):
    last = state["selection_messages"][-1]
    return "table_select_tools" if getattr(last, "tool_calls", None) else "validate_selection"

def route_after_validate_selection(state):
    sel = state.get("selection")
    if sel and sel.needs_clarification:
        return "clarify_or_reject"
    if sel and sel.tables and not state.get("last_error"):
        return "schema_render"
    if state.get("selection_retry_count", 0) < MAX_SELECTION_RETRY:
        return "table_select"
    return "clarify_or_reject"

def route_after_validate_sql(state):
    if state["validation"] and state["validation"].ok:
        return "execute"
    if state.get("last_error") == "cannot_fix":
        return "failure_answer"
    if state.get("repair_attempts", 0) < MAX_REPAIR_ATTEMPTS:
        return "sql_rewrite"
    return "failure_answer"

def route_after_execute(state):
    if state.get("execution") is not None:
        return "summarize"
    if state.get("last_error") == "cannot_fix":
        return "failure_answer"
    if state.get("repair_attempts", 0) < MAX_REPAIR_ATTEMPTS:
        return "sql_rewrite"
    return "failure_answer"

约定：

路由函数只读 State、不写 State，不 import nodes/。

cannot_fix 短路在预算判断之前，立即终止，不继续消耗预算。

route_after_validate_selection 用 last_error 区分“合法”和“非法”，validate_selection 是唯一写入点。

两个循环共用 sql_rewrite 节点，但入口边分别来自 validate_sql 和 execute，sql_rewrite 只读 validation。

5.4 失败与重试
场景	处理	上限
选表返回不存在的表	反馈合法表清单，重试选表，selection_retry_count+1	1 次
选表结果为多组不连通表	提示需要 JOIN，重试选表，selection_retry_count+1	1 次
选表解析失败	反馈格式要求，重试选表，selection_retry_count+1	计入 1 次预算
需要澄清（问题歧义/无相关表）	停止流程，返回澄清问题或“不支持”	—
SQL 校验失败	sql_rewrite 修复后重新校验	与执行错误共享 3 次
SQL 执行运行错误	带错误信息 + 失败 SQL 交给改写 Agent	共享 3 次
执行超时	带 TIMEOUT 提示改写	共享 3 次
改写 Agent 返回 cannot_fix	立即终止，路由到 failure_answer，不继续消耗预算	短路
查询结果为空	不重试，汇总阶段明确回答“未查询到符合条件的数据”	—
汇总 Agent 失败	降级输出：Markdown 表格 + 行数 + 最终 SQL	—

5.5 图装配草图（graph.py）
from functools import partial
from langgraph.graph import StateGraph, END

def build_graph(catalog, agents):
    g = StateGraph(SQLAgentState)

    g.add_node("table_select",       partial(table_select_node,       catalog=catalog, agent=agents.table_selector))
    g.add_node("table_select_tools", partial(table_select_tools_node, catalog=catalog))
    g.add_node("validate_selection", partial(validate_selection_node, catalog=catalog))
    g.add_node("schema_render",      partial(schema_render_node,      catalog=catalog))
    g.add_node("sql_generate",       partial(sql_generate_node,       agent=agents.sql_generator))
    g.add_node("validate_sql",       partial(validate_sql_node,       catalog=catalog))
    g.add_node("sql_rewrite",        partial(sql_rewrite_node,        agent=agents.sql_rewriter))
    g.add_node("execute",            partial(execute_node,            catalog=catalog))
    g.add_node("summarize",          partial(summarize_node,          agent=agents.summarizer))
    g.add_node("clarify_or_reject",  clarify_or_reject_node)
    g.add_node("failure_answer",     failure_answer_node)

    g.set_entry_point("table_select")

    g.add_conditional_edges("table_select", route_after_select, {
        "table_select_tools": "table_select_tools",
        "validate_selection": "validate_selection",
    })
    g.add_edge("table_select_tools", "table_select")

    g.add_conditional_edges("validate_selection", route_after_validate_selection, {
        "table_select": "table_select",
        "schema_render": "schema_render",
        "clarify_or_reject": "clarify_or_reject",
    })
    g.add_edge("schema_render", "sql_generate")
    g.add_edge("sql_generate", "validate_sql")
    g.add_conditional_edges("validate_sql", route_after_validate_sql, {
        "execute": "execute",
        "sql_rewrite": "sql_rewrite",
        "failure_answer": "failure_answer",
    })
    g.add_edge("sql_rewrite", "validate_sql")
    g.add_conditional_edges("execute", route_after_execute, {
        "summarize": "summarize",
        "sql_rewrite": "sql_rewrite",
        "failure_answer": "failure_answer",
    })
    g.add_edge("summarize", END)
    g.add_edge("clarify_or_reject", END)
    g.add_edge("failure_answer", END)

    return g  # 返回未 compile 的图，compile() 在调用方做

装配约定：

build_graph 用 functools.partial 注入 catalog / agents，catalog 不进 State。

返回未 compile 的 StateGraph，compile() 在调用方做，便于测试按需挂 InMemorySaver。

v1 澄清走终止返回，不需要 checkpointer；后续做多轮追问时再加。

6. 各 Agent 详细设计
四个 Agent 共用 StructuredAgent（llm.py），差异只在 output_schema、system_prompt、temperature、tools。模型统一 deepseek-flash。

6.0 StructuredAgent 编码约定
Agent 在模块级定义为 StructuredAgent 实例，不在每次请求时新建。

链在首次 ainvoke 时懒构建，导入模块和跑单元测试不需要 DEEPSEEK_API_KEY。

用 ChatDeepSeek + bind_tools([output_schema] + tools, tool_choice="auto")，不用 with_structured_output。

必须带 extra_body={"thinking": {"type": "disabled"}}：deepseek-flash 默认开启思考模式，思考模式会拒绝强制 tool_choice（Thinking mode does not support this tool_choice），且 temperature 不生效。关闭 thinking 是结构化输出可用的前提。

解析顺序：先取 AIMessage.tool_calls 的参数，再回退解析正文 JSON（兼容代码块）；两者都失败时抛 StructuredOutputParseError，不在 Agent 内部重试，由节点层决定。

SQL_AGENT_TOOL_CHOICE 默认 auto，保留改为具体输出模型名强制调用的后门，但默认不启用。

用户输入放进 <question> 标签并声明“仅作为数据”，避免提示注入。

6.1 TableSelectAgent
目的：把自然语言问题映射到最少的表集合，不生成 SQL，不做连接推理。

输入：用户问题 + 目录摘要（表名、行数、列名列表、外键边）；可调用 get_table_schema(table) 工具。

输出：TableSelection。

工具：get_table_schema，白名单校验，只允许访问 11 张业务表。

系统提示要点：

你是 SQLite 数据库分析专家。根据用户问题，从给定表清单中选择回答所需的最少表集合。

规则：
1. 只能从清单中选择表，禁止臆造表名；
2. 多表问题必须返回所有需要的表；
3. 不要生成 SQL，不要猜测连接条件；
4. 如果问题与数据库无关、信息不足或存在歧义，将 needs_clarification
   设为 true，并提出一个具体的澄清问题；
5. 只输出结构化结果。

模型配置：deepseek-flash，temperature=0。

失败处理：表名非法、不连通、解析失败由 validate_selection 统一处理，递增 selection_retry_count；不在此 Agent 内重试。

6.2 SQLGeneratorAgent
目的：在已选表范围内，把问题转成一条可执行的 SQLite SELECT。

输入：用户问题 + 已选表详细 schema（字段、类型、可空、distinct、min/max、mode、3 行样例）+ 外键连接关系 + 方言说明（SQLite）。

输出：SQLDraft（cannot_fix 恒为 False）。

工具：无。生成阶段不执行或校验 SQL。

系统提示要点：
你是 SQLite SQL 专家。只使用给定的表、列和连接关系生成 SQL。

规则：
1. 只生成一条 SELECT 或 WITH ... SELECT 语句；
2. 禁止 INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/PRAGMA/ATTACH；
3. 表名、列名必须与 schema 完全一致（Chinook 列名为 PascalCase）；
4. 多表查询使用显式 JOIN，不依赖隐式笛卡尔积；
5. 需要排序的结果给出确定性 ORDER BY；
6. 明细查询默认 LIMIT 200；聚合查询不加 LIMIT；
7. 日期使用 SQLite 语法（如 strftime），不要使用 MySQL 函数；
8. 输出 sql、explanation、assumptions。

模型配置：deepseek-flash，temperature=0。

失败处理：生成结果由 SQLValidator 统一校验，不在此 Agent 内重试。

6.3 SQLRewriteAgent
目的：根据精确错误修复 SQL，不重新回答整个问题。

输入：用户问题 + 已选表 schema 与连接关系 + 当前失败 SQL + ValidationResult（错误码 + 原始错误信息）+ 已尝试过的 SQL 列表 + 当前修复次数。

输出：SQLDraft，cannot_fix=True 时 sql 为空且必须给 cannot_fix_reason。

工具：无。防止模型通过工具反复试错绕过预算。

系统提示要点：

你是 SQLite SQL 修复专家。只修复给定 SQL 中导致错误的部分，保持用户原始查询意图不变。

规则：
1. 根据错误码定位问题：unsafe / syntax / unknown_object / ambiguous / runtime / timeout；
2. 只使用给定 schema 中的表和列；
3. 不要通过改变业务含义来“绕过”错误；
4. 不要重复已失败的 SQL；
5. 如果问题本身无法用当前数据库回答，返回 cannot_fix=true 并说明原因。

模型配置：deepseek-flash，temperature=0.2。

失败处理：修复后必须重新经过 SQLValidator；共享 3 次修复预算；cannot_fix 短路终止。

6.4 ResultSummaryAgent
目的：把结构化结果转成忠实、可读的中文答案。

输入：用户问题 + 最终 SQL + 列名 + 结果行（最多 50 行进入 prompt；超过则提供前 50 行 + 总行数）+ row_count + truncated。

输出：FinalAnswer。

工具：无。

系统提示要点：
你是数据分析助手。只依据给定的 SQL 查询结果回答用户问题。

规则：
1. 数字必须与结果一致，不得编造或外推；
2. 结果是多行时，给出整体结论并列举关键数据；
3. 结果为空时，明确回答“未查询到符合条件的数据”，不要猜测原因；
4. 结果被截断时，在 caveats 中说明只展示了部分数据；
5. 不要修改 SQL，不要声称执行了未提供的查询；
6. evidence 中列出支撑结论的具体数值。

模型配置：deepseek-flash，temperature=0.3。

降级策略：summarize 节点内 try/except，LLM 调用失败时输出 Markdown 表格 + 总行数 + 最终 SQL，stage 写 summarize_fallback。

7. 工具与上下文装配

7.1 SchemaCatalog
用 SQLAlchemy inspect(engine) 获取业务表；不使用裸 sqlite_master，避免包含 sqlite_sequence / sqlite_stat1。

一次解析所有列：类型、可空、distinct、缺失数、min/max、mode、3 行样例。

记录外键边，构建无向连接图，提供 is_connected(tables)。

进程级单例；以 DB 文件 mtime 作为缓存失效条件；可选序列化到 artifacts/schema_profile.json。

参考实现初始化约 0.8 秒，不要每个请求重新解析。

不实现 check_sql：notebook 的 DBParser.check_sql 通过 engine.begin() 真执行并提交，不得复用。

两种渲染视图：

视图	使用方	内容
render_catalog()	table_select	表名、行数、列名列表、外键边
render_schema(tables)	sql_generate / sql_rewrite	完整字段统计、3 行样例、所选表之间的 JOIN 边

7.2 工具权限边界
Agent	可用工具
TableSelectAgent	get_table_schema(table)（白名单校验）
SQLGeneratorAgent	无
SQLRewriteAgent	无
ResultSummaryAgent	无
Orchestrator（图节点内代码）	validate_sql、execute_sql（仅代码内部调用）
不要把 execute_sql 暴露给生成或改写 Agent，否则模型可能通过工具反复试错，绕过校验和重试预算。

7.3 table_select 工具子循环（路径 B）
get_table_schema 提升为图节点 table_select_tools，工具调用在图层面上可见、可日志、可单测。

table_select 节点每次被调用时只返回一条 AIMessage；table_select_tools 返回 ToolMessage 列表；validate_selection 在非法时追加反馈 HumanMessage。

子循环退出条件由 route_after_select 判断“最后一条消息有无 tool_calls”，不由模型决定。

重试时保留历史：selection_messages 非空则直接复用，不重置 system + user。

8. 安全与可靠性
风险	措施
模型生成写操作	只读连接 + 单语句 + SELECT|WITH 白名单 + 危险关键字拒绝（多层防御）
多语句注入	拒绝分号分隔的多语句；校验前去除尾分号
访问内部表	catalog 只暴露 11 张业务表；工具和生成 prompt 均使用白名单
查询过慢/全表扫描	5 秒超时 + EXPLAIN QUERY PLAN 日志；必要时在汇总中提示
大结果拖垮上下文	执行层 200 行截断；汇总层最多 50 行 + 总额
无限修复循环	共享 3 次修复上限 + cannot_fix 短路 + 总 LLM 调用上限
选表无限重试	selection_retry_count 独立上限 1
API key 泄露	只从环境变量读取 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL；日志脱敏；notebook 中的硬编码 key 不得复用
提示注入	用户问题作为数据传入；schema 只来自 catalog；输出使用结构化契约
思考模式兼容性	extra_body={"thinking": {"type": "disabled"}} 强制关闭；M0 冒烟阶段验证
只读连接：

python
engine = create_engine("sqlite:///file:ref/chinook.db?mode=ro&uri=true")
该 URL 已验证可阻止写入。校验和执行使用同一配置。可选加固：sqlite3.Connection.set_authorizer 仅允许读操作。

9. 可观测性
9.1 三层分工
层	手段	负责什么	v1 必须
结构化日志	astream(stream_mode="updates") + log_node_update	每个节点的 stage、耗时、表、SQL、错误码、计数器	是
回调补充	TokenUsageLogger	LLM 的 token 用量、模型名	推荐
外部追踪	LangSmith / OTel（可选）	跨请求 trace 树、节点嵌套	可选，不阻塞

9.2 run_workflow：消费端统一打点
async def run_workflow(question, catalog, agents, obs):
    graph = build_graph(catalog, agents).compile()
    config = {"callbacks": [TokenUsageLogger()]} if obs.enable_callback_logger else {}

    start_time = time.perf_counter()
    last_time = start_time
    final_answer = None

    async for chunk in graph.astream({"question": question}, stream_mode="updates", config=config):
        now = time.perf_counter()
        for node_name, update in chunk.items():
            log_node_update(node_name, update, now - last_time, start_time)
            if update.get("answer") is not None:
                final_answer = update["answer"]
        last_time = now

    if final_answer is None:
        final_answer = FinalAnswer(answer="工作流未产生最终答案。")
    return final_answer

约定：

节点函数内部不出现 logger.info，所有日志由 log_node_update 从 update 增量中提取。

节点耗时用 chunk 间隔近似，精确耗时交给回调层或外部追踪（v1 可选）。

终止节点的 answer 从 update 里直接取，不依赖 get_state。

final_answer is None 时构造明确失败答案，不静默返回 None。

9.3 日志格式与脱敏
每个阶段输出一行 key=value 日志到 stderr，最终 JSON 输出到 stdout：

text
2026-10-22 23:46:11 | INFO | sql_agent.workflow | stage=validate_sql elapsed=0.001s ok=True code=None total=1.234s
2026-10-22 23:46:11 | INFO | sql_agent.workflow | stage=execute elapsed=0.000s rows=1 truncated=False total=1.235s
用户问题、SQL、错误信息压缩为单行并截断（SQL 200 字符，错误 100 字符）。

不记录 API key；不输出完整 rows 和 schema_context。

TokenUsageLogger 在 on_llm_end 和 on_llm_error 各打一行，LLM 失败有独立日志行。

日志级别通过 SQL_AGENT_LOG_LEVEL 控制，默认 INFO。

10. 评测与测试
10.1 金标生成
notebook 的 10 处问题及处理：
#	位置	问题	处理
1	table_names[:1]	只处理第一张表	必须修复：遍历全部 11 张业务表
2	循环末尾 break	处理完第一张表就退出	必须修复：删除 break
3	if len(sql_answer) > 1: continue	多行结果被丢弃	必须修复：保留多行，金标记录 expected_rows 列表
4	check_sql() 真执行	不是 dry-run	不得复用：替换为 SQLValidator
5	strip('').replace('sql\n','')| 去围栏方式误伤 | 用strip_code_fence` 统一处理 |		
6	question_prompt 只生成计数统计	覆盖面不可控	必须替换：人工种子 + query_type 矩阵
7	字段组合爆炸	成本不可控	必须替换：query_type 矩阵控制规模
8	问题与 SQL 一次成对生成	无法定位哪侧错	必须替换：问题与 SQL 解耦
9	独立 answer_rewrite_prompt	与线上分布不一致	必须替换：用线上同款 ResultSummaryAgent
10	question_rewrite_prompt	只改问题不验证 SQL	保留思路 + 加固：变体重走 SQL 验证

新流程五阶段：
阶段 1：种子问题（人工）→ seeds.py 按 query_type 手写，绑定 gold_tables
阶段 2：SQL 验证（LLM + 确定性）→ SQLGeneratorAgent + SQLValidator + SQLExecutor
阶段 3：变体扩展（LLM）→ 改写 prompt，变体重新走阶段 2 SQL 验证
阶段 4：nl_answer 生成（线上同款 ResultSummaryAgent）
阶段 5：人工抽检 → review.csv，JOIN/GROUP BY/日期/TopN 必须 human

金标契约（scripts/gold/models.py）：
class GoldItem(BaseModel):
    id: str
    question: str
    query_type: Literal[
        "single_agg", "single_detail", "join_2", "join_3",
        "group_having", "date_filter", "top_n", "empty", "irrelevant",
    ]
    gold_tables: list[str]
    gold_sql: str
    expected_columns: list[str]
    expected_rows: list[list[str]]             # 已字符串化、已排序
    row_count: int
    nl_answer: str | None = None
    source: Literal["manual", "llm_variant"]
    parent_id: str | None = None
    verified_by: Literal["human", "auto"] | None = None
    notes: str = ""

覆盖面矩阵（总计约 50 条）：

query_type	最少条数	代表性表/链路
single_agg	10	albums, tracks, invoices, customers
single_detail	8	customers, employees, tracks
join_2	8	albums↔artists, tracks↔albums, invoices↔customers
join_3	5	invoice_items→invoices→customers
group_having	5	tracks GROUP BY GenreId
date_filter	4	invoices.InvoiceDate
top_n	4	按销售额/数量排序
empty	3	任意表
irrelevant	3	无
人工 review 规则：join_2 / join_3 / group_having / date_filter / top_n 必须 verified_by="human"；single_agg / single_detail / empty / irrelevant 可 auto-pass。金标入库 gold_v1.jsonl，走 PR 流程。

10.2 评测指标
评测脚本读 gold_v1.jsonl，对每条调用 run_workflow，收集四个指标：

指标	计算方式	通过阈值
执行结果匹配	分别执行 gold_sql 和 agent SQL，比较排序后的行多重集	≥ 0.90
选表召回	set(gold_tables) ⊆ set(agent_selection.tables)	≥ 0.95
修复能力	注入错误 SQL，看 3 次预算内是否修复	≥ 0.80
答案忠实度	nl_answer 中数字必须能在 expected_rows 中找到	违例率 ≤ 0.05
按 query_type 分组报告，n/a 保留不填 0。特殊样本判定：

empty：row_count == 0 且 answer 含“未查询到”语义且 repair_attempts == 0。

irrelevant：走 clarify_or_reject 路径。

date_filter：strftime 正确，执行结果匹配。

答案忠实度用正则抽数字 + 集合比对，不用 LLM judge，只对 verified_by="human" 样本启用。

0.3 测试分层与 mock 策略
核心原则：能用确定性代码验证的逻辑，绝不让 LLM 参与；必须验证图结构的场景，用脚本化 Agent 替代真实模型调用。

目录：

text
tests/
  conftest.py
  unit/
    test_catalog.py  test_validator.py  test_executor.py
    test_nodes.py    test_routes.py     test_models.py
  workflow/
    test_retry_budget.py  test_selection_retry.py
    test_empty_result.py  test_summary_fallback.py
  integration/
    test_live_deepseek.py
pytest 配置：asyncio_mode="auto"、addopts="-m 'not integration'"、markers=["integration"]。

fixture：

catalog：scope="session"，真实 ref/chinook.db，不 mock。

scripted_agents：scope="function"，四个 Agent 的 AsyncMock。

build_test_graph：scope="function"，返回工厂函数，不默认挂 checkpointer。

tmp_db：scope="function"，tmp_path 临时 DB 供 executor 测试，不碰 ref/chinook.db。

mock 边界：

层	mock 什么	不 mock 什么
单元（db）	无（executor 用 tmp_db）	SQLite、EXPLAIN
单元（nodes）	StructuredAgent.ainvoke	节点内状态增量逻辑
单元（routes）	无	路由函数本身
工作流	四个 Agent 的 ainvoke	图结构、条件边、catalog、validator、executor
集成	无	全部真实组件
必须避免的反模式：工作流测试 mock 节点本身（绕过计数器递增）；executor 测试直接操作 ref/chinook.db；单元测试 mock SchemaCatalog；集成测试断言具体答案值；只断言 repair_attempts 不断言 call_count。

工作流必测五场景：

场景	关键断言
修复预算耗尽	repair_attempts == 3 且 call_count == 3，走 failure_answer
cannot_fix 提前终止	repair_attempts == 1 且 call_count == 1
选表重试独立预算	selection_retry_count == 1 且 repair_attempts == 0
空结果不重试	row_count == 0 且 repair_attempts == 0 且 call_count == 0
汇总降级	图不崩溃，answer 是 Markdown 表格，stage == "summarize_fallback"

11. 代码结构
11.1 设计约束
确定性组件与 LLM 组件物理分离：db/ 不 import langchain_* / langgraph / agents/。

图装配与节点实现分离：graph.py 只做 add_node / add_edge / add_conditional_edges，节点函数放 nodes/。

可观测性不侵入节点：节点内不出现 logger.info，日志由 observability.py 消费 astream(updates) 时统一打点。

11.2 目录树
text
src/sql_agent/
  __init__.py
  config.py                 # DeepSeekSettings + ObservabilitySettings + MAX_* 常量
  state.py                  # SQLAgentState (TypedDict)
  models.py                 # Pydantic 契约
  llm.py                    # StructuredAgent：懒加载、bind_tools、解析顺序、关闭 thinking
  observability.py          # log_node_update / TokenUsageLogger / run_workflow
  db/
    __init__.py
    catalog.py              # SchemaCatalog
    validator.py            # SQLValidator
    executor.py             # SQLExecutor
  agents/
    __init__.py             # 导出四个模块级 StructuredAgent 实例
    table_selector.py
    sql_generator.py
    sql_rewriter.py
    result_summarizer.py
  nodes/
    __init__.py
    selection.py            # table_select / table_select_tools / validate_selection
    generation.py           # schema_render / sql_generate
    validation.py           # validate_sql
    repair.py               # sql_rewrite
    execution.py            # execute
    summary.py              # summarize（含降级）
    terminal.py             # clarify_or_reject / failure_answer
  routes.py                 # 四个路由函数
  graph.py                  # build_graph(catalog, agents)
  cli.py                    # 对外入口
tests/
  conftest.py
  unit/  workflow/  integration/
scripts/
  smoke_deepseek.py         # M0 冒烟
  build_gold.py             # M9 金标入口
  gold/
    models.py  seeds.py  sql_verify.py  expand.py  summarize.py  review.py  io.py
artifacts/
  schema_profile.json       # 可选
ref/
  chinook.db                # 素材，只读
  sql-agent.ipynb           # 行为参考，不 import
11.3 依赖方向
text
cli.py
  → observability.run_workflow
  → graph.build_graph
      → nodes/*         → db/catalog, db/validator, db/executor
                        → agents/* → llm.StructuredAgent → config
      → routes.py       （只读 State，不 import nodes）
  → db/catalog.load     （图外注入）
三条硬约束：

db/ 不得 import agents/、llm.py、langgraph、langchain_*。

routes.py 不得 import nodes/。

nodes/ 不得 import graph.py。

11.4 与 ref/sql-agent.ipynb 的对应
notebook 组件	新设计对应	处理方式
DBParser.__init__ 遍历所有表做统计	SchemaCatalog.load()	保留思路，加缓存、去副作用、样例改 3 行
DBParser.get_table_sample（fetchone() 单行）	render_schema() 的 3 行样例	必须修复为 3 行
DBParser.check_sql（真执行）	SQLValidator（EXPLAIN dry-run）	不得复用
DBParser.execute_sql	SQLExecutor	保留思路，加只读、超时、截断
SQLTableSelectAgent（qwen-max + parse_table）	TableSelectAgent（deepseek-flash + 白名单工具）	模型统一、工具加白名单、prompt 结构化
SQLGeneratorAgent（未完成）	SQLGeneratorAgent	按 6.2 补齐
SQLResultSummaryAgent（未完成）	ResultSummaryAgent	按 6.4 补齐
ask_gpt（qwen-plus）	统一走 StructuredAgent + deepseek-flash	去掉自由文本解析
gt_qes_answer 生成循环	第 10.1 节金标生成	修复 [:1] + break，扩展 query_type 矩阵
最后 cell 的“手动进行推理”注释	第 2 节原则 5	作为“代码编排”的原始依据

12. 实施顺序
12.1 排序原则
外部不确定性最先冒烟：deepseek-flash 关闭思考模式后的 tool_choice / 结构化输出 / cannot_fix 填充率是最大未知，必须先验证。

确定性组件先于 LLM 组件：catalog、validator、executor 不依赖模型，先做完并单测通过。

每个阶段结束 CI 必须绿：不允许“先写完全部再统一调试”。

12.2 阶段总览
阶段	内容	依赖	关键验收
M0	地基 + deepseek-flash 冒烟	无	冒烟脚本三次运行通过
M1	SchemaCatalog	M0	test_catalog.py 全绿
M2	SQLValidator + SQLExecutor	M1	test_validator.py + test_executor.py 全绿
M3	State + routes + graph 骨架 + 桩节点	M0	图能编译，桩节点跑通全路径
M4	正常路径节点	M1/M2/M3	单表查询端到端跑通
M5	修复回路	M4	预算/cannot_fix 场景全绿
M6	终止与降级	M4	空结果、无关问题、降级路径全绿
M7	可观测性 + CLI	M4	结构化日志输出，CLI 可调用
M8	工作流测试补全	M5/M6	tests/workflow/ 全绿，默认 CI 通过
M9	金标生成 + 评测	M4 完成即可启动	gold_v1.jsonl 入库，评测报告产出
关键路径：M0→M1→M2→M3→M4→M5→M8。M6/M7 与 M5 并行，M9 在 M4 后即可启动。

12.3 各阶段验收要点
M0：关闭 thinking 后 tool_choice=auto 可用；SQLDraft 连续 3 次解析成功；cannot_fix=True 时 sql 为空且给原因。

M1：只暴露 11 张业务表；render_schema 含 3 行样例；is_connected 正确；缓存命中 < 10ms。

M2：DROP TABLE→UNSAFE；多语句→UNSAFE；EXPLAIN 是唯一发送给 DB 的语句；250 行输入截断到 200；递归 CTE 5 秒超时；mode=ro 拒绝写入。

M3：图能 compile()；桩节点跑通 table_select→...→summarize；test_routes.py 穷举所有分支含 cannot_fix 短路。

M4：--question "albums 表里有多少张专辑" 返回“347 张专辑”；子循环正确退出；summarize 只接收前 50 行。

M5：预算耗尽 repair_attempts==3 且 call_count==3；cannot_fix 时 repair_attempts==1 且 call_count==1；改写后回 validate_sql。

M6：空结果 repair_attempts==0；无关问题走 clarify_or_reject；选表重试 selection_retry_count==1 且 repair_attempts==0；汇总降级不崩溃。

M7：stderr 逐节点 key=value 日志；stdout 输出 FinalAnswer JSON；日志无 API key；TokenUsageLogger 输出 token。

M8：pytest -m "not integration" 全绿，总耗时 < 30 秒；五个必测场景各有用例；工作流测试不 mock 节点本身。

M9：种子覆盖 9 类 query_type 达最少条数；SQL 全部通过 validator；五个复杂类型 verified_by="human"；评测报告按 query_type 分组。

13. 已确定与待确认

13.1 已确定
架构与编排

编排由 LangGraph StateGraph 负责；主流程路由由确定性条件边控制，不交给 LLM 自主决定下一步。

SchemaCatalog 图外依赖注入，不进 SQLAgentState。

table_select 子循环采用路径 B：get_table_schema 提升为图节点，工具调用在图层面上可见。

sql_rewrite 之后必须回 validate_sql，不直接去 execute。

cannot_fix 在两个条件边中短路到 failure_answer，不继续消耗预算。

State 与计数器

repair_attempts（上限 3）和 selection_retry_count（上限 1）放入 State，由确定性节点递增，条件边只读不写。

两个计数器独立，选表重试不占用 SQL 修复预算。

sql_rewrite 入口第一行递增 repair_attempts（“进入即消耗”）。

selection_messages 用 add_messages reducer，重试时保留历史。

契约与节点行为

SQLDraft 扩展 cannot_fix + cannot_fix_reason，model_validator 强制互斥。

StructuredAgent._parse 先 tool_calls 再正文 JSON，两者都失败抛异常，不在 Agent 内部重试。

execute 失败时返回 {"execution": None, "validation": 错误包装}，sql_rewrite 只从 validation 读错误。

summarize 降级在节点内 try/except，stage 写 summarize_fallback。

v1 澄清走终止返回，不引入 interrupt + checkpointer。

模型与 LLM 配置

全部 Agent 统一 deepseek-flash，不按节点分模型。

ChatDeepSeek 必须带 extra_body={"thinking": {"type": "disabled"}}，关闭思考模式是 tool_choice 和 temperature 生效的前提。

temperature：选表/生成 0，改写 0.2，汇总 0.3。

tool_choice 默认 auto，SQL_AGENT_TOOL_CHOICE 保留后门，默认不启用。

可观测性

三层：结构化日志（必须）→ 回调 token（推荐）→ 外部追踪（可选）。

日志由 observability.py 消费 astream(updates) 统一打点，节点内不写 logger.info。

节点耗时用 chunk 间隔近似，精确耗时交给回调层。

TokenUsageLogger 自研最小实现，不引入第三方可观测性库。

测试与评测

三层测试：单元 / 工作流（脚本化 Agent）/ 集成（环境变量开关）。

mock 停在 StructuredAgent.ainvoke，不 mock 节点本身。

executor 测试用 tmp_path 临时 DB，不碰 ref/chinook.db。

工作流必测五场景，计数器 + call_count 双断言。

金标四阶段解耦：人工种子 → SQL 确定性验证 → 变体扩展（重走验证）→ 线上同款 Summary → 人工抽检。

金标约 50 条覆盖 9 类 query_type，五个复杂类型必须 verified_by="human"。

评测四指标：执行结果匹配（多重集）、选表召回（子集）、修复能力、答案忠实度（正则数字比对，不用 LLM judge）。

代码结构与实施

依赖方向单向：db/ 不依赖 LLM；routes.py 不依赖 nodes/；nodes/ 不依赖 graph.py。

graph.py 只做装配，返回未 compile 的图。

v1 入口为 CLI。

实施顺序 M0–M9，M0 冒烟最先，M4 是分水岭，M6/M7 与 M5 并行，M9 可与 M5/M6/M7 并行。

ref/sql-agent.ipynb 三处必须修复/不得复用：check_sql 真执行、单行样例、金标循环 [:1]+break。

13.2 待确认
schema_profile.json 是否持久化到 artifacts/：当前是进程级内存缓存 + mtime 失效；持久化可减少冷启动解析时间，但需处理文件版本与 DB 版本一致性。

多轮追问的交互方式：v1 已定为终止返回澄清；v2 若需多轮，引入 checkpointer + interrupt，clarify_or_reject 改为 interrupt(...)，图结构不需大改。

外部追踪是否接入：LangSmith 零配置但 SaaS；OTel/Phoenix/Langfuse 可自托管。v1 用结构化日志 + 回调已满足要求，外部追踪作为配置开关保留。

deepseek-flash 在复杂 JOIN 上的评测表现：若 M9 评测显示 join_3 / group_having 执行匹配率低于阈值，再评估是否切换模型或优化 prompt，但 v1 不预置模型切换逻辑。

文档结束。 本文档为 v1 完整设计，可直接作为实现依据。实施从 M0 冒烟阶段开始，按第 12 节顺序推进。
