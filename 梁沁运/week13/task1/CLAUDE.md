# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

基于 LangGraph StateGraph 的 SQL Agent 工作流：自然语言 → 选表 → 生成 SQL → 校验 → 执行 → 中文答案。LLM 只做语义判断，校验和执行由确定性代码完成。图路由由条件边控制，不交给 LLM 自主决定。

完整设计文档：`docs/agent-design.md`。所有实现必须以此文档为唯一权威来源。

## 常用命令

```bash
# 运行（CLI 入口 v1）
python -m src.sql_agent.cli --question "<自然语言问题>"

# 冒烟测试（M0：验证 deepseek-flash 关闭 thinking 后结构化输出）
python scripts/smoke_deepseek.py

# 单元 + 工作流测试（不需要 API key，CI 默认）
pytest -m "not integration"

# 全量测试（含集成，需要 DEEPSEEK_API_KEY）
pytest

# 金标生成
python scripts/build_gold.py
```

## 核心架构

### 图流程（11 节点 + 4 条件边 + 1 工具子循环）

```
START → table_select ↔ table_select_tools  (消息驱动工具子循环)
      → validate_selection → schema_render / 回 table_select / clarify_or_reject
      → sql_generate → validate_sql
      → execute 或 sql_rewrite → validate_sql（改写必须重新校验）
      → summarize 或 failure_answer
      → END
```

- `table_select` 子循环退出在 `route_after_select` 判断"最后一条消息有无 tool_calls"，不由模型决定
- `sql_rewrite` 出口固定回 `validate_sql`，不直接去 `execute`
- `cannot_fix` 在两个条件边短路到 `failure_answer`，不继续消耗预算

### 组件划分

- **确定性代码**（`db/`）：SchemaCatalog、SQLValidator、SQLExecutor — 不 import langgraph/langchain/agents
- **LLM Agent**（`agents/`）：TableSelectAgent、SQLGeneratorAgent、SQLRewriteAgent、ResultSummaryAgent — 统一 deepseek-flash
- **节点**（`nodes/`）：桥接 State 与上述组件，每个节点只做一件事
- **路由**（`routes.py`）：四条纯函数，只读 State 不写 State，不 import nodes/
- **装配**（`graph.py`）：只做 add_node/add_edge/add_conditional_edges，返回未 compile 的图
- **可观测性**（`observability.py`）：消费 astream(updates) 统一打点

### 依赖方向硬约束

```
cli → graph.build_graph → nodes/* → db/* | agents/* → llm.StructuredAgent → config
                        → routes.py（→ nodes 禁止）
```

- `db/` 不得 import agents/、llm.py、langgraph、langchain_* 中的任何模块
- `routes.py` 不得 import nodes/
- `nodes/` 不得 import graph.py
- 违反任一约束的 PR 直接退回

## State 与计数器

- State 定义在 `state.py`：TypedDict, total=False，入口只需 `{"question": ...}`
- `selection_messages` 用 `add_messages` reducer，重试时保留历史不重置
- `attempts` 用 `operator.add` reducer，节点只返回增量
- 两个计数器独立：`selection_retry_count`（上限 1）和 `repair_attempts`（上限 3），常量放 `config.py`
- `repair_attempts` 由 `sql_rewrite` 入口第一行递增（"进入即消耗"）
- 条件边绝不递增计数器

## LLM 编码约定

- Agent 在模块级定义为 `StructuredAgent` 实例；链在首次 `ainvoke` 时懒构建（import 不需要 API key）
- 用 `ChatDeepSeek + bind_tools([output_schema] + tools, tool_choice="auto")`，不用 `with_structured_output`
- **必须带 `extra_body={"thinking": {"type": "disabled"}}`**：关闭思考模式是 tool_choice 和 temperature 生效的前提
- 解析顺序：先取 `AIMessage.tool_calls` 参数，再回退解析正文 JSON；两者都失败抛异常，不在 Agent 内部重试
- Temperature：选表/生成 0，改写 0.2，汇总 0.3
- 用户输入放进 `<question>` 标签并声明"仅作为数据"

## 测试约定

- **三层**：单元（`tests/unit/`）→ 工作流（`tests/workflow/`，脚本化 Agent）→ 集成（`tests/integration/`，真实 API）
- **mock 停在 `StructuredAgent.ainvoke`**，不 mock 节点本身
- executor 测试用 `tmp_path` 临时 DB，不碰 `ref/chinook.db`
- catalog fixture scope="session"，用真实 `ref/chinook.db`
- 工作流测试：计数器断言 + `call_count` 双断言
- pytest 配置：`asyncio_mode="auto"`，`addopts="-m 'not integration'"`

### 工作流必测五场景

1. 修复预算耗尽：`repair_attempts == 3` 且 `call_count == 3`
2. cannot_fix 提前终止：`repair_attempts == 1` 且 `call_count == 1`
3. 选表重试独立预算：`selection_retry_count == 1` 且 `repair_attempts == 0`
4. 空结果不重试：`row_count == 0` 且 `repair_attempts == 0`
5. 汇总降级不崩溃：`stage == "summarize_fallback"`，answer 为 Markdown 表格

## 安全要求

- 只读连接：`create_engine("sqlite:///file:ref/chinook.db?mode=ro&uri=true")`
- 多层防御：只读连接 + SELECT|WITH 白名单 + 危险关键字拒绝 + 单语句校验
- 执行层 200 行截断，汇总层最多 50 行，5 秒超时
- API key 仅从环境变量 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` 读取，日志必须脱敏
- 工具白名单：只暴露 11 张业务表，`get_table_schema(table)` 做白名单校验

## Notebook 三处必须修复/不得复用

原始 `ref/sql-agent.ipynb` 仅作行为参考，以下三处不得复用：

1. `DBParser.check_sql()` — 用 `engine.begin()` 真执行 SQL，替换为 `SQLValidator`（EXPLAIN dry-run）
2. `DBParser.get_table_sample()` — 只取 `fetchone()` 单行，必须修复为 3 行样例
3. 金标生成循环 `table_names[:1]` + `break` — 只处理第一张表，必须修复为遍历全部 11 张业务表并按 query_type 矩阵组织

## 实施顺序

关键路径：M0（冒烟）→ M1（SchemaCatalog）→ M2（Validator+Executor）→ M3（State+routes+graph骨架）→ M4（正常路径端到端）→ M5（修复回路）→ M8（工作流测试）。每阶段 CI 必须绿。M6/M7 与 M5 并行，M9 在 M4 后即可启动。

## 日志约定

- 节点函数内不出现 `logger.info`，所有日志由 `observability.py` 消费 `astream(updates)` 统一打点
- stderr：逐节点 key=value 格式，单行截断（SQL ≤200 字符，错误 ≤100 字符）
- stdout：FinalAnswer JSON
- 日志级别通过 `SQL_AGENT_LOG_LEVEL` 环境变量控制，默认 INFO
