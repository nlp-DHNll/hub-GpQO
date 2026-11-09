# sql-agent-langgraph（week13 作业一）

作业：**使用 LangGraph 复现之前的 sql agent**（week12 `sql-agent-langchain`）。

week12 版已经是 LangChain + LangGraph 混合实现（StateGraph 编排 + LCEL chain），
因此本周把「复现」做成一次**新课特性重做**：四角色 prompt、DB 安全三件套、
数据契约、重试预算与降级策略**原样继承**（行为等价），编排层按 week13 课件
五讲重写——修复循环封装为子图、AsyncSqliteSaver 持久化支撑多轮对话与回放。

## week13 课件特性对照

| 课件（`02_langgraph教程/`） | 本项目落点 |
| --- | --- |
| `01_graph_api基础` | 主图 `StateGraph`：`table_select → generate → repair(子图) → summarize`，条件边路由，共享重试预算 3 次 |
| `02_funciton_api基础`（Functional API） | 未采用，见「已知取舍」 |
| `03_持久化` | `compile(checkpointer=...)` 可插拔；CLI/回放/服务端统一 `AsyncSqliteSaver` 落盘 `ref/checkpoints.sqlite`，`thread_id` 为会话主键 |
| `04_回放` | `replay.py`：`aget_state_history` 列快照 + 从「generate 之后」的 checkpoint 重放 |
| `05_子图调用` | 修复循环 `validate ⇄ execute → rewrite` 封装为 `RepairState` 子图，父子状态经包装节点显式转换 |
| `01_langchain教程/06_流式输出` | REPL 用 `astream(stream_mode="updates")` 实时打印节点进度 |

## 与 week12 版的差异

| 维度 | week12（sql-agent-langchain） | week13（本项目） |
| --- | --- | --- |
| 主图节点 | 6 个（validate/execute/rewrite 平铺在主图） | 4 个（修复循环移入子图） |
| 修复循环 | 主图回边 | `RepairState` 子图（独立 schema，显式状态转换，课件 05 写法） |
| 持久化 | 无 checkpointer | `AsyncSqliteSaver` 落盘，进程重启可恢复会话 |
| 多轮对话 | 不支持（单问单答） | 同 `thread_id` 续跑：上一轮问答注入 `history`，追问/指代可理解 |
| 澄清提问 | 一次性返回，是死路 | 真多轮：澄清后补充回答，同 thread 续跑走完全链路 |
| CLI | 单问 JSON | 单问 JSON（兼容）+ 多轮 REPL（`/reset` `/resume` `/thread`） |
| 回放 | 无 | `replay.py` 演示 checkpoint 重放 |

继承不变的部分：`db/`（SchemaCatalog / SQLValidator / SQLExecutor：只读连接、
EXPLAIN 编译校验、关键字门禁、超时与行数限制）、`agents/` 四角色 system prompt
与温度（选表 0 / 生成 0 / 改写 0.2 / 汇总 0.3）、防注入 `<question>` 包裹、
`WorkflowOutput` 数据契约、汇总失败降级 Markdown 表格。

## 架构

```text
主图（QueryState）                          修复子图（RepairState）
START → table_select ─┐
        │(需澄清)→ END │(选表成功)
        ↓              ↓
      generate → repair ──投影──→ START → validate ─ok→ execute ─成功→ END
                   ↑                ↑(失败,预算内)      │(失败,预算内)
                   └────映射回────── rewrite ←───────────┘
                   ↓(执行成功)
                summarize → END
```

- `repair` 是子图的包装节点：进入时把 `question/schema_context/sql/attempts`
  投影给子图，退出时把 `attempts/validation/execution/final` 映射回主图；
- 子图内预算耗尽或 `cannot_fix` 时组装 `final` 终止，主图路由见 `final` 即 END；
- 多轮：`prepare_turn()` 每轮从 checkpoint 读上一轮 `final` 组装 `history`
  （最近 6 轮），并**显式重置**一轮字段（残留的 `final` 会让路由误判已终止）；
  `history` 注入选表与生成 Agent 的 prompt，改写/汇总不注入（职责单一）。

## 目录结构

```text
src/sql_agent/
  config.py            # 配置：读项目根 .env；新增 checkpoint_db（SQL_AGENT_CHECKPOINT_DB）
  logging_config.py    # 日志到 stderr（与 week12 一致）
  models.py            # 数据契约：+ ChatTurn/RepairState/QueryState.history
  llm.py               # ChatOpenAI 工厂（继承）
  checkpoint.py        # AsyncSqliteSaver 工厂（open_checkpointer 异步上下文）
  db/                  # 确定性组件：catalog / validator / executor（继承）
  agents/              # 4 个 LLM chain（继承）
  graph.py             # 主图 + 修复子图 + 多轮 history 组装
  cli.py               # 单问 JSON + 多轮 REPL（进度流式打印）
  replay.py            # checkpoint 回放演示
  __main__.py
tests/
  test_db_tools.py     # db 组件单测（继承）
  test_logging.py      # 日志配置测试（继承）
  test_graph.py        # 图工作流测试：mock chain + 多轮/子图/持久化新用例
ref/chinook.db         # Chinook SQLite（不入库；从 week12 复制或重新放置）
ref/checkpoints.sqlite # checkpoint 落盘（运行产物，不入库）
```

## 运行

依赖在 conda 环境 `py312`（langchain 1.3 / langgraph 1.2 /
langgraph-checkpoint-sqlite + aiosqlite）。

```bash
# 单问模式：最终 JSON 在 stdout，进度日志在 stderr（week12 兼容）
PYTHONPATH=src python -m sql_agent "总共有多少张专辑？"

# 多轮 REPL：追问自动带上一轮上下文；/reset 新会话、/resume 恢复历史会话
PYTHONPATH=src python -m sql_agent

# 指定会话续跑（跨进程恢复）
PYTHONPATH=src python -m sql_agent "那销量前三呢？" --thread <thread_id>

# checkpoint 回放演示
PYTHONPATH=src python -m sql_agent.replay
```

凭据从项目根 `.env` 读取（`API_KEY` / `BASE_URL` / `BASE_MODEL`）。

## 测试

```bash
pytest -q          # 26 个测试，无需 API key（LLM 调用全部 mock）
```

新增用例（相对 week12 的 23 个）：

- `test_multi_turn_history_injected`：第二轮同 thread 提问，上一轮问答出现在
  选表与生成 Agent 的 prompt 中；
- `test_clarification_then_followup`：澄清 → 补充回答的完整闭环；
- `test_rewrite_path_in_subgraph`：坏 SQL 在子图内修复（原重试用例的子图版）；
- `test_sqlite_saver_persistence_across_instances`：落盘后新 saver 实例
  （模拟进程重启）恢复会话，且 `prepare_turn` 正确组装 history 并重置残留字段。

## 冒烟记录（真实 LLM，qwen3.8-max，2026-11-04）

| 场景 | 输入 | 结果 |
| --- | --- | --- |
| 单问 JSON | 总共有多少张专辑？ | ✅ 347 张，`SELECT COUNT(*)`，0 次修复 |
| REPL 多轮 | 「总共有多少张专辑？」→「那其中销量最高的三张是哪些？」 | ✅ 同 thread 续跑，正确理解「其中」，三表 JOIN 聚合，前三名销量/收入正确 |
| 跨进程恢复 | 新进程 `/resume <thread>` 后「接着刚才的排名，第 4 名是哪张专辑？」 | ✅ 理解排名上下文，ROW_NUMBER 窗口函数取第 4 名 |
| 澄清提问 | 帮我分析一下销量 | ✅ ❓ 返回维度/指标/时间范围澄清问题，未生成 SQL |
| checkpoint 回放 | `python -m sql_agent.replay` | ✅ 6 个快照列出，从「generate 之后」重放成功（repair/summarize 重跑，答案措辞变化可证 LLM 重新调用） |

## 已知取舍

- **Functional API（@entrypoint/@task）未采用**：课件五讲特性已覆盖四个
  （Graph API / 持久化 / 回放 / 子图），主流程用 StateGraph 表达更贴合作业的
  图编排主题；Functional API 适合以代码为中心的流程，对本项目无增量收益。
- **子图内部进度不出现在主图 updates 流**：子图作为普通节点函数被调用，其
  validate/execute/rewrite 的流转在 stderr 日志（`stage=validate` 等）可查。
- **全线使用 AsyncSqliteSaver 而非同步 SqliteSaver**：图入口（`ainvoke`/`astream`）
  全是异步路径，langgraph-checkpoint-sqlite 3.x 的同步 saver 不支持 async
  方法（`aget_tuple` 直接 `NotImplementedError`），实测踩坑后统一异步版。
- **改写/汇总 Agent 不注入多轮历史**：修复只看当前 SQL 与错误，汇总只看当前
  执行结果，注入历史反而引入干扰；只有选表与生成需要理解追问。
