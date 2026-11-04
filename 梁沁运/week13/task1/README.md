# SQL Agent — 基于 LangGraph 的自然语言查询 Agent

一个**可观测、可控、确定性路由**的 SQL Agent 工作流：将自然语言问题转换为对 Chinook 数据库的只读 SQL 查询，执行并返回中文答案。

## 概览

```
用户问题 → 选表 → 校验表选择 → 渲染 Schema → 生成 SQL → 校验 SQL
                                                    ↓
                                               ┌─ 修复回路 ─┐
                                               ↓            ↑
                                             执行 → 结果汇总 → 中文答案
```

核心设计思路：**LLM 只做语义判断，校验和执行必须是确定性代码**。图由 LangGraph StateGraph 编排，条件边由确定性路由函数控制，LLM 不自主决定下一步。

完整设计文档：[docs/agent-design.md](docs/agent-design.md)

## 组件清单

| 组件 | 类型 | 职责 |
|------|------|------|
| `SchemaCatalog` | 确定性代码 | 解析 DB 结构、缓存 schema/统计/外键/样例 |
| `TableSelectAgent` | LLM | 根据问题选最少表集合 |
| `SQLGeneratorAgent` | LLM | 基于 schema 生成 SQLite SELECT |
| `SQLValidator` | 确定性代码 | 安全检查 + EXPLAIN 编译校验 |
| `SQLRewriteAgent` | LLM | 根据错误码修复 SQL |
| `SQLExecutor` | 确定性代码 | 只读执行、超时、截断 |
| `ResultSummaryAgent` | LLM | 结果转中文答案 |

## 关键设计决策

- **LLM 只做语义判断**：选表、写 SQL、修复 SQL、汇总结果
- **校验/执行必须是确定性代码**：LLM 不能批准自己生成的 SQL，不能直接持有写权限
- **一个 Agent 一个决策**：避免超长 prompt 同时负责多件事
- **主流程由确定性条件边控制**：循环退出、重试预算、最终答案路由都不交给 LLM
- **失败有界**：修复上限 3 次，选表重试上限 1 次，`cannot_fix` 短路终止
- **依赖单向**：`db/` 不依赖 LLM 组件，`routes.py` 不依赖 `nodes/`，`nodes/` 不依赖 `graph.py`

## 状态机

StateGraph 11 个节点 + 4 条条件边 + 1 个工具子循环：

- `table_select` ↔ `table_select_tools` — 消息驱动的工具调用子循环
- `validate_selection` → 合法则 `schema_render`，非法且预算未耗尽则回 `table_select`
- `schema_render` → `sql_generate` → `validate_sql`
- 校验失败 → `sql_rewrite` → 回 `validate_sql`（改写必须重新校验）
- 执行失败 → `sql_rewrite` → 回 `validate_sql`
- 成功 → `summarize` → END

`cannot_fix` 在两个条件边中短路到 `failure_answer`，不继续消耗预算。

## 技术栈

- **编排**：LangGraph StateGraph
- **LLM**：DeepSeek Flash（统一模型，关闭 thinking mode）
- **数据库**：SQLite（Chinook，只读连接 `mode=ro`）
- **结构化输出**：Pydantic BaseModel + `bind_tools`
- **可观测性**：`astream(updates)` 消费层 + `TokenUsageLogger`

## 快速开始

### 前置条件

- Python ≥ 3.10
- `DEEPSEEK_API_KEY` 环境变量（可选配置 `DEEPSEEK_BASE_URL`）

### 安装

```bash
# 1. 克隆项目后进入目录
cd task1

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -e ".[dev]"
```

### 运行

```bash
# CLI 单次查询
python -m src.sql_agent.cli --question "albums 表里有多少张专辑"

# 查看日志（stderr 结构化日志 + stdout JSON 答案）
python -m src.sql_agent.cli --question "每位客户的总消费金额" 2>logs.txt
```

### 冒烟测试

```bash
# M0：验证 deepseek-flash 关闭 thinking 后结构化输出正常
python scripts/smoke_deepseek.py
```

## 项目结构

```
src/sql_agent/
  __init__.py
  config.py              # DeepSeek 配置 + 常量（MAX_REPAIR_ATTEMPTS 等）
  state.py               # SQLAgentState TypedDict
  models.py              # Pydantic 契约：TableSelection, SQLDraft, FinalAnswer 等
  llm.py                 # StructuredAgent：懒加载、bind_tools、解析
  observability.py       # log_node_update / TokenUsageLogger / run_workflow
  db/
    catalog.py           # SchemaCatalog：解析 DB、缓存 schema、连通性
    validator.py         # SQLValidator：安全检查 + EXPLAIN 编译校验
    executor.py          # SQLExecutor：只读执行、超时、截断
  agents/
    table_selector.py    # TableSelectAgent
    sql_generator.py     # SQLGeneratorAgent
    sql_rewriter.py      # SQLRewriteAgent
    result_summarizer.py # ResultSummaryAgent
  nodes/
    selection.py         # table_select / table_select_tools / validate_selection
    generation.py        # schema_render / sql_generate
    validation.py        # validate_sql
    repair.py            # sql_rewrite
    execution.py         # execute
    summary.py           # summarize（含降级）
    terminal.py          # clarify_or_reject / failure_answer
  routes.py              # 四条条件边路由函数
  graph.py               # build_graph(catalog, agents)
  cli.py                 # 对外 CLI 入口

tests/
  conftest.py
  unit/                  # catalog, validator, executor, nodes, routes, models
  workflow/              # 图结构测试：重试预算、选表重试、空结果、降级
  integration/           # 真实 deepseek-flash 端到端

scripts/
  smoke_deepseek.py      # M0 冒烟
  build_gold.py          # M9 金标入口
  gold/                  # 金标生成：seeds, sql_verify, expand, summarize, review

ref/
  chinook.db             # 素材数据库，只读
  sql-agent.ipynb        # 行为参考（不 import）

docs/
  agent-design.md        # 完整设计文档
```

## 依赖方向

```
cli.py
  → observability.run_workflow
  → graph.build_graph
      → nodes/*      → db/catalog, db/validator, db/executor
                      → agents/* → llm.StructuredAgent → config
      → routes.py    (只读 State，不 import nodes)
  → db/catalog.load  (图外注入)
```

**硬约束**：
- `db/` 不 `import` agents/、llm.py、langgraph、langchain_*
- `routes.py` 不 `import` nodes/
- `nodes/` 不 `import` graph.py

## 测试

```bash
# 单元 + 工作流测试（不依赖 API key）
pytest -m "not integration"

# 包含真实 API 调用的集成测试
pytest -m "integration"       # 需要有 DEEPSEEK_API_KEY

# 全部测试
pytest
```

### 测试分层

| 层 | mock 什么 | 不 mock 什么 |
|----|-----------|-------------|
| 单元（db） | 无（executor 用 tmp_db） | SQLite、EXPLAIN |
| 单元（nodes） | StructuredAgent.ainvoke | 节点内状态增量逻辑 |
| 单元（routes） | 无 | 路由函数本身 |
| 工作流 | 四个 Agent 的 ainvoke | 图结构、条件边、catalog、validator、executor |
| 集成 | 无 | 全部真实组件 |

### 工作流必测五场景

1. 修复预算耗尽 → `repair_attempts == 3`，走 `failure_answer`
2. `cannot_fix` 提前终止 → `repair_attempts == 1`
3. 选表重试独立预算 → `selection_retry_count == 1` 且 `repair_attempts == 0`
4. 空结果不重试 → `row_count == 0` 且 `repair_attempts == 0`
5. 汇总降级不崩溃 → `stage == "summarize_fallback"`

## 安全措施

| 风险 | 措施 |
|------|------|
| 写操作 | 只读连接 (`mode=ro`) + SELECT/WITH 白名单 + 危险关键字拒绝 |
| 多语句注入 | 拒绝分号分隔的多语句 |
| 内部表访问 | catalog 只暴露 11 张业务表，白名单校验 |
| 慢查询 | 5 秒超时 + EXPLAIN QUERY PLAN 日志 |
| 大结果 | 执行层 200 行截断，汇总层最多 50 行 |
| 无限循环 | 修复上限 3 + `cannot_fix` 短路 |
| API key 泄露 | 仅从环境变量读取，日志脱敏 |
| 提示注入 | 用户问题用 `<question>` 标签隔离 |

## 金标评测

金标约 50 条，覆盖 9 类 query_type：`single_agg`, `single_detail`, `join_2`, `join_3`, `group_having`, `date_filter`, `top_n`, `empty`, `irrelevant`。

评测四指标：

| 指标 | 计算方式 | 通过阈值 |
|------|----------|----------|
| 执行结果匹配 | gold_sql 与 agent SQL 的行多重集比较 | ≥ 0.90 |
| 选表召回 | gold_tables ⊆ agent_selection.tables | ≥ 0.95 |
| 修复能力 | 注入错误 SQL，3 次预算内修复 | ≥ 0.80 |
| 答案忠实度 | nl_answer 中数字必须在 expected_rows 中 | 违例率 ≤ 0.05 |

## 实施阶段

| 阶段 | 内容 | 关键验收 |
|------|------|----------|
| M0 | 地基 + deepseek-flash 冒烟 | 关闭 thinking 后结构化输出可用 |
| M1 | SchemaCatalog | 11 张业务表、3 行样例、连通性 |
| M2 | SQLValidator + SQLExecutor | 安全检查、EXPLAIN、超时、截断 |
| M3 | State + routes + graph 骨架 | 图可编译，桩节点跑通 |
| M4 | 正常路径节点 | 单表查询端到端跑通 |
| M5 | 修复回路 | 预算/cannot_fix 全绿 |
| M6 | 终止与降级 | 空结果、无关问题、降级全绿 |
| M7 | 可观测性 + CLI | 结构化日志，CLI 可调用 |
| M8 | 工作流测试补全 | tests/workflow/ 全绿 |
| M9 | 金标生成 + 评测 | gold_v1.jsonl 入库，评测报告 |

关键路径：M0 → M1 → M2 → M3 → M4 → M5 → M8

## 参考资料

- [docs/agent-design.md](docs/agent-design.md) — 完整设计文档（v1.0）
- [ref/sql-agent.ipynb](ref/sql-agent.ipynb) — 行为参考 notebook
- [ref/chinook.db](ref/chinook.db) — Chinook 示例数据库（SQLite，只读）
