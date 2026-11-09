# week13 作业总览

本周两项作业，从“把 Agent 编排清楚”到“把 Agent 用起来”：

| 作业 | 内容 | 入口 | 测试 |
| --- | --- | --- | --- |
| [作业一：LangGraph 版 SQL Agent](作业一/README.md) | 用 LangGraph 复现 week11 的 Chinook SQL Agent | `cd 作业一 && python run.py "总共有多少张专辑？"` | 38 passed |
| [作业二：SQL Agent 网页聊天](作业二/README.md) | 给作业一配一个可用的聊天前端与 SSE 接口 | `cd 作业二 && python run.py --demo` | 13 passed |

![网页界面](作业二/docs/preview.png)

---

## 1. 目录结构

```text
week13/
├── README.md                       # 本文件
├── 作业一/
│   ├── README.md                   # 图设计、节点、条件边、与 week11 对照
│   ├── run.py                      # CLI 入口
│   ├── demo_offline.py             # 无需 Key 的图演示
│   ├── sql_agent_lg/               # LangGraph 实现
│   ├── data/chinook.db             # Chinook 测试库
│   └── tests/                      # 38 个离线测试
└── 作业二/
    ├── README.md                   # 前端、API、SSE、多轮改写说明
    ├── run.py                      # Web 启动入口（支持 --demo）
    ├── backend/                    # FastAPI + ChatService + 演示模式
    ├── static/                     # 聊天页面（HTML/CSS/JS）
    ├── tests/                      # 13 个接口与流程测试
    └── docs/                       # 界面截图
```

两个目录必须保持兄弟关系：作业二的 `backend/paths.py` 会把 `../作业一` 加入 `sys.path`，直接复用 `sql_agent_lg`，不复制代码。

---

## 2. 快速验证

### 2.1 作业一：命令行版

```bash
cd 作业一
pip install -r requirements.txt

# 不需要 Key：确认数据库、查看 LangGraph 流程图、跑图演示
python run.py --show-catalog
python run.py --show-graph
python demo_offline.py

# 需要 Key：真实模型问答
copy .env .env      # 填入 DEEPSEEK_API_KEY
python run.py "总共有多少张专辑？"

# 测试
pytest                      # 38 passed
```

### 2.2 作业二：网页版

```bash
cd 作业二
pip install -r requirements.txt

# 无需 Key：离线演示（SQL 真实执行，选表/生成/汇总用内置逻辑）
python run.py --demo

# 或配置 Key 后走真实 LangGraph
copy .env .env      # 填入 DEEPSEEK_API_KEY
python run.py

# 测试
pytest                      # 13 passed
```

浏览器访问 <http://127.0.0.1:8000>。Windows 也可以直接双击：

- `作业二/启动.bat`：真实模型模式；
- `作业二/离线演示.bat`：无需 Key 的演示模式。

---

## 3. 两个作业的关系

```text
week11  openai-agents 线性 Workflow
   │
   │  作业一：换成 LangGraph 状态机（节点 + 条件边 + 修复回边）
   ▼
作业一  sql_agent_lg
   │
   │  作业二：加 Web 层（聊天 UI + SSE + 多轮改写 + 结果渲染）
   ▼
作业二  FastAPI + 原生前端
```

分工边界：

- **作业一**负责单轮语义：选表、生成 SQL、校验、执行、修复、汇总；
- **作业二**负责会话与展示：多轮追问改写、SSE 进度、表格/SQL/轨迹渲染；
- 两边共用同一套 `WorkflowOutput` / `ExecutionResult` 数据契约和安全策略；
- LLM 只做语义判断，校验、执行、重试预算、最终 JSON 组装都由确定性代码控制。

---

## 4. 关键设计

### 4.1 作业一的图

```text
START
  → select_tables
      ├─(需要澄清 / 非法) → clarify → finalize
      └─(合法) → load_schema → generate_sql → validate_sql
            ├─(校验通过) → execute_sql
            │     ├─(0 行)                 → empty_result → finalize
            │     ├─(>0 行)                → summarize    → finalize
            │     └─(执行错误且有预算)     → rewrite_sql
            ├─(校验失败且有预算)           → rewrite_sql
            └─(预算耗尽)                   → fail → finalize

rewrite_sql → validate_sql（回到校验，修复预算共享）
```

校验失败和执行失败**共享**最多 3 次修复预算；空结果不重试；预算耗尽走明确失败。

### 4.2 作业二的两条接口

- `POST /api/chat`：一次性返回完整 `ChatResponse`，方便脚本或第三方调用；
- `POST /api/chat/stream`：SSE 逐条推送 `start` / `stage` / `final` / `[DONE]`，页面实时显示执行过程。

### 4.3 离线演示不是假数据

`python run.py --demo` 不调用大模型，但 SQL 仍然经过作业一的只读执行器，真实查询 `chinook.db`。页面会把模式明确标成“离线演示”，并在回答里附加 caveat，方便没有 Key 的评审环境直接看效果。

---

## 5. 配置与密钥

- 两个作业都只从环境变量 / `.env` 读取 Key；
- 仓库中只有 `.env.example`，没有任何真实密钥；
- `.env` 已加入 `.gitignore`；
- 默认服务为 DeepSeek（`deepseek-chat`），也支持阿里云百炼（DashScope）和 OpenAI 兼容端点；
- 作业二会依次读取 `作业二/.env`、`作业一/.env` 和系统环境变量。

---

## 6. 测试结果

在本机 Python 3.13 + `langgraph 1.2.x` 环境下：

```text
作业一：38 passed
作业二：13 passed
```

测试全部离线：

- 作业一用脚本化 Agent + 真实 SQLite 校验/执行；
- 作业二用假图 + TestClient 验证 REST/SSE/多轮改写，演示模式用例真实读取 Chinook。

---

## 7. 备注

- 两个作业的中文注释、提示词、文档与用户可见文案均为中文；
- 作业二前端使用原生 HTML/CSS/JS，无构建步骤，双击启动即可；
- 更详细的图设计见 [作业一/README.md](作业一/README.md)，接口与页面说明见 [作业二/README.md](作业二/README.md)。
