# sql-agent-web（week13 作业二）

作业：**结合作业一，给一个前端，用户在网页输入文本通过对话查询到 SQL Agent 执行结果。**

架构（前后端分离，对应课件「前后端分离的应用架构」主题）：

```text
Vue 3 + Vite + Element Plus          FastAPI + sse-starlette         作业一 LangGraph
┌──────────────────────┐   POST /api/chat (SSE)   ┌──────────────┐   ┌─────────────────┐
│ 聊天页：会话侧栏/气泡流 │ ───────────────────────▶ │ 事件流翻译层   │──▶│ SQLAgentGraph    │
│ 阶段进度/SQL/打字机答案 │ ◀─────────────────────── │ astream(updates)│  │ 主图+修复子图     │
└──────────────────────┘                          └──────────────┘   └────────┬────────┘
        │  GET /api/history（checkpoint 还原轮次）                              │
        └────────────────────────────────────────────────── AsyncSqliteSaver ─┘
                                                            data/checkpoints.sqlite
```

- **backend/**：FastAPI（8001），复用作业一的 `SQLAgentGraph`（`sys.path` 注入
  `../作业一/sql-agent-langgraph/src`，不复制代码）；`AsyncSqliteSaver` 落盘，
  服务重启会话不丢。
- **frontend/**：Vue 3 + Vite（5173）+ Element Plus；dev server proxy 转发 `/api`。

## SSE 事件协议（POST /api/chat）

| event | data | 时机 |
| --- | --- | --- |
| `meta` | `{thread_id}` | 流开始（前端保存用于续问） |
| `progress` | `{node, stage}` | 主图每个节点完成（真实流式：选表→生成→修复子图→汇总） |
| `sql` | `{sql}` | `stage=executed`（可执行 SQL，前端代码块展示） |
| `clarification` | `{question}` | 选表判定需澄清（同 thread 补充后继续） |
| `result` | `WorkflowOutput` 全字段 | 最终答案 |
| `error` | `{message}` | 异常 |
| `done` | `{}` | 流结束 |

`GET /api/history?thread_id=`：从 checkpoint 还原该会话全部轮次（`history` + 当前
`final`），前端「切换会话」时回填消息流。

## 前端交互

- **会话侧栏**：`thread_id` 列表存 localStorage（标题取第一问），「新会话」开新
  thread；点击切换时经 `/api/history` 恢复全部轮次；
- **assistant 气泡**：阶段步骤行（小圆点逐个点亮，真实 SSE 事件驱动）→ SQL 代码块
  → 答案（Markdown 渲染，含降级表格）→ 元信息标签（表/行数/修复次数）→ caveats；
- **打字机**：answer 逐字放出。**取舍**：汇总 Agent 是 `with_structured_output`
  （function calling），token 级流式只能拿到工具参数碎片、拼不出可读文本，因此
  真实流式体现在阶段进度事件，打字机为前端渲染节奏；
- **演示辅助**：URL hash 支持 `#q=<问题>`（自动发送）与 `#t=<thread_id>`（自动
  恢复会话），用于冒烟与截图；
- 澄清提问以警告卡片展示，用户直接在输入框补充，同 thread 续问。

## 运行

```bash
# 1) 后端（conda py312）：FastAPI 8001
cd backend
/opt/miniconda3/envs/py312/bin/python -m uvicorn main:app --port 8001

# 2) 前端（node v20，经 nvs）：Vite 5173
cd frontend
npm install
npm run dev        # 打开 http://localhost:5173
```

凭据仍从项目根 `.env` 读取（由作业一的 `sql_agent.config` 处理）。

## 测试与质量

```bash
cd backend && /opt/miniconda3/envs/py312/bin/python -m pytest test_api.py -q   # 6 passed（LLM 全 mock）
/opt/miniconda3/envs/py312/bin/python -m ruff check main.py test_api.py        # All checks passed
cd frontend && npm run build                                                    # 构建通过
```

## 冒烟记录（真实 LLM，qwen3.8-max，2026-11-04，截图见 `screenshots/`）

| 截图 | 场景 | 结果 |
| --- | --- | --- |
| `01-首页与输入框.png` | 空状态 | ✅ 侧栏/输入框/空提示正常 |
| `02-首轮问答.png` | 「销量最高的三张专辑是哪些？」 | ✅ 阶段步骤逐个点亮（选表→生成→执行→汇总），SQL 代码块、答案、表/行数标签、caveats 齐全 |
| `03-多轮会话恢复.png` | 同会话追问「那第 4 名是哪张专辑？」 | ✅ 理解销量排名上下文，ROW_NUMBER 取第 4 名；切换会话从 checkpoint 恢复全部轮次 |

API 层冒烟（curl）：

- 多轮追问：同 thread 问「那第 4 名」→ 三表 JOIN + 窗口函数，`《Acústico》22 件` ✅
- 澄清闭环：模糊问题触发 `clarification` 事件 → 补充「按销量，就是卖出件数」→
  同 thread 续跑出正确答案（`LIMIT 1 OFFSET 3`）✅
- `/api/history`：两轮后返回完整轮次（问题/答案/SQL/元信息）✅

## 已知取舍

- **token 级流式**：结构化输出（function calling）无连续可读 token，真实流式为
  阶段进度事件；answer 打字机是前端渲染效果（见上）；
- **会话列表存 localStorage**：`thread_id` 的权威数据在 checkpoint 库，列表仅在
  当前浏览器持久化；跨设备同步不在作业范围；
- **SSE 行尾**：实测不同链路（TestClient/浏览器 fetch）SSE 行尾 `\n`/`\r\n`
  不一致，前后端解析均做了兼容（各自踩坑后修复）；
- **#q/#t 演示参数**：仅为截图/冒烟便利，不影响正常交互。
