# sql-agent-langchain

用 **LangChain / LangGraph** 复刻课件参考项目（openai-agents 实现，不随仓库
分发）的 Chinook SQL Agent 工作流：

**数据库解析 → 表选择 → SQL 生成 → SQL 校验 → SQL 改写 → SQL 执行 → 结果汇总**

行为、数据契约（Pydantic models）、重试预算（共享 3 次修复）、安全策略
（只读连接 + EXPLAIN 校验 + 关键字门禁）与原版完全一致，仅替换了
LLM 框架与编排层。

## 与 openai-agents 版的对应关系

| openai-agents 版 | LangChain/LangGraph 版 | 说明 |
| --- | --- | --- |
| `Agent(instructions=..., output_type=X)` | `ChatPromptTemplate + ChatOpenAI.with_structured_output(X)` | LCEL chain，模块级定义（`src/sql_agent/agents/`） |
| `Runner.run(agent, prompt)`（async） | `chain.ainvoke({"prompt": prompt})` | system=instructions，human=拼装好的上下文 |
| `ModelSettings(temperature=...)` | `ChatOpenAI(temperature=...)` | 选表/生成 0，改写 0.2，汇总 0.3 |
| `workflow.py` 显式 Python 状态机 | `graph.py` 的 `StateGraph` | 循环/重试由条件边表达（见下） |
| `with trace("SQLAgentWorkflow")` | LangSmith（设 `LANGSMITH_TRACING=true`） | 代码无需改动 |
| `AsyncOpenAI + base_url` 接线 | `llm.py` 的 `make_llm()` 工厂 | 显式传 api_key/base_url，兼容端点统一走 function calling 结构化输出 |

编排差异说明：原版用 `for 循环 + if 分支` 控制重试；LangGraph 版把每个阶段
建成节点，用条件边表达回边：

```text
START → table_select → generate → validate ⇄ execute → summarize → END
                        ↑            ↘(校验/执行失败,预算内)
                        └──── rewrite ←──┘
```

- `validate` / `execute` 失败且 `repair_attempts < 3` → `rewrite` → 回到 `validate`
- `rewrite` 返回 `cannot_fix` → 直接 END（输出原因）
- 预算耗尽 → END（输出"已达到最大修复次数"）
- 结果为空 → 跳过汇总 Agent，固定回答"未查询到符合条件的数据。"
- 汇总 Agent 调用失败 → 降级为 Markdown 表格输出

## 目录结构

```text
src/sql_agent/
  config.py            # 配置：读项目根 .env（API_KEY/BASE_URL/BASE_MODEL），兼容 OPENAI_*
  logging_config.py    # 日志到 stderr（与原版一致）
  models.py            # Pydantic 数据契约（与原版一致，QueryState 兼作图状态）
  llm.py               # ChatOpenAI 工厂（对应原版 agents/__init__.py 的模型接线）
  db/                  # 确定性组件，与原版一致：catalog / validator / executor
  agents/              # 4 个 LLM chain：table_selector / sql_generator / sql_rewriter / result_summarizer
  graph.py             # LangGraph StateGraph 编排（对应原版 workflow.py）
  cli.py               # CLI 入口
tests/
  test_db_tools.py     # db 组件单测（与原版一致）
  test_logging.py      # 日志配置测试（与原版一致）
  test_graph.py        # 图工作流测试：mock chain，覆盖重试/预算/澄清/降级路径
ref/chinook.db         # Chinook SQLite 数据库（课件自带，不入库，需自行放置到 ref/ 下）
```

## 运行

依赖已在 conda 环境 `py312` 中（langchain 1.3 / langchain-openai 1.4 / langgraph 1.2）。

```bash
# 从本目录运行；凭据自动从项目根 .env 读取（API_KEY / BASE_URL / BASE_MODEL）
PYTHONPATH=src python -m sql_agent "总共有多少张专辑？"

# 模型覆盖（可选）
SQL_AGENT_MODEL=qwen3.8-max SQL_AGENT_SUMMARY_MODEL=qwen3.8-max \
  PYTHONPATH=src python -m sql_agent "哪个客户的消费总金额最高？"

# 日志在 stderr，最终 JSON 在 stdout
PYTHONPATH=src python -m sql_agent "前 3 张专辑是什么？" --log-level DEBUG
```

## 测试

```bash
pytest -q          # 23 个测试，无需 API key（LLM 调用全部 mock）
ruff check src tests
```

冒烟（真实 LLM，2026-10-28，qwen3.8-max，终端截图见 `../screenshots/`）：

| 截图 | 问题 | 路径 | 结果 |
| --- | --- | --- | --- |
| `01-单表聚合查询.png` | 总共有多少张专辑？ | 单表聚合 | ✅ 347 张，0 次修复 |
| `02-多表JOIN查询.png` | 哪个客户的消费总金额最高？ | 两表 JOIN | ✅ Helena Holý 49.62，0 次修复 |
| `03-无关问题澄清路径.png` | 帮我写一首关于秋天的诗 | 无关问题 | ✅ 返回澄清问题，未生成 SQL |
| `04-pytest与ruff检查.png` | `pytest -q` + `ruff check src tests` | 质量检查 | ✅ 23 passed / All checks passed |
