# AGENTS.md

## Repo state

- LangChain 复刻版：基于 `D:\xue\00-sql-agent`（openai-agents 版）的 SQL Agent，用 LangChain 重写 Agent 层。
- 工作流与数据契约与原版完全一致：**DB 解析 → 表选择 → SQL 生成 → SQL 校验 → SQL 改写/修复 → 执行 → 结果汇总**。
- 设计文档沿用 `D:\xue\00-sql-agent\docs\agent-design.md`；本项目未复制该文档，改动前先读原文档。
- 框架无关的确定性组件（`db/catalog.py`、`db/validator.py`、`db/executor.py`、`models.py`、`config.py`、`logging_config.py`）与原版相同，未改动语义。
- 与原版的唯一差异在 `agents/` 与 `workflow.py`：

| 原版（openai-agents） | 本版（LangChain） |
| --- | --- |
| `Agent(model=..., output_type=...)` | `build_*_chain()`：`ChatPromptTemplate \| ChatOpenAI.with_structured_output(schema, method="function_calling")` |
| `Runner.run(agent, prompt)` | `get_*_chain().ainvoke({"input": prompt})` |
| 模块级 Agent 单例 | `get_*_chain()` 进程级单例（懒加载） |

- 为什么 `method="function_calling"`：langchain-openai 1.x 的 `with_structured_output` 默认 `json_schema`（OpenAI Structured Output），DeepSeek 等 OpenAI 兼容端点不支持；`function_calling` 走工具调用，与原版 SDK 的 `output_type` 机制一致。
- 为什么懒加载：`ChatOpenAI` 构造时就校验 API Key（langchain-openai 1.x），懒加载保证导入包 / 跑测试无需 Key。

## Environment / commands

- 依赖：`langchain>=1.0`、`langchain-openai>=1.0`、`sqlalchemy>=2.0`（已在本机 Anaconda Python 3.13 验证：langchain 1.3.11、langchain-openai 1.4.1、sqlalchemy 2.0.43）。
- 本机有多个 Python：`python` 指向 Doubao 沙箱运行时（无 langchain）；**用 `D:\anaconda\python.exe` 运行本项目**。
- 运行 CLI（在项目根目录，PowerShell）：
  `$env:PYTHONPATH="src"; & "D:\anaconda\python.exe" -m sql_agent "总共有多少张专辑？"`
  需要 `OPENAI_API_KEY`；`OPENAI_BASE_URL` 默认 `https://api.deepseek.com`（兼容 OpenAI 协议）。
- 运行测试（无需 API Key，LLM 链被 mock）：`& "D:\anaconda\python.exe" -m pytest -q`
- 日志输出到 stderr，最终 JSON 输出到 stdout；`--log-level DEBUG|INFO|WARNING|ERROR` 或 `SQL_AGENT_LOG_LEVEL` 控制级别。
- 模型覆盖：`SQL_AGENT_MODEL`（默认 `deepseek-flash`）、`SQL_AGENT_SUMMARY_MODEL`（默认 `deepseek-flash`）。

## Database facts

- SQLAlchemy `inspect(engine).get_table_names()` 返回 11 张业务表；裸 `sqlite_master` 还包含 `sqlite_sequence`、`sqlite_stat1`，需过滤 `sqlite_%`。
- 表：`albums`(347)、`artists`(275)、`customers`(59)、`employees`(8)、`genres`(25)、`invoice_items`(2240)、`invoices`(412)、`media_types`(5)、`playlist_track`(8715)、`playlists`(18)、`tracks`(3503)。
- 列名 PascalCase（`ArtistId`、`InvoiceDate`、`UnitPrice`），表名小写；生成 SQL 与 prompt 中必须保持原样。

## Implementation constraints

- 所有 DB 访问只读：SQLAlchemy 用 `sqlite:///file:<url-encoded-abs-path>?mode=ro&uri=true`；裸 sqlite3 用 `Path.as_uri()?mode=ro`。
- `SQLValidator` 只用 `EXPLAIN` 编译，从不执行；安全门禁先于编译：单语句、SELECT/WITH 前缀、字符串/注释外禁止危险关键字。
- `SQLExecutor` 只读执行：`PRAGMA query_only=ON`、5 秒超时（`set_progress_handler`）、200 行截断、2000 字符单元格截断。
- 修复预算：校验失败与执行失败共享 `max_repair_attempts`（默认 3）次改写；空结果不重试，汇总阶段输出"未查询到符合条件的数据。"。
- 测试 mock 的是 `workflow` 模块里的 `get_*_chain()` 返回的链（FakeChain 共享输出队列），不触发网络调用。
- 注释、docstring、prompt、面向用户的答案保持中文，与原版一致。
