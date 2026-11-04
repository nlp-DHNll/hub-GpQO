# Task2 — SQL Agent 前端

用户在网页输入自然语言问题，通过对话查询 SQL Agent 执行结果。

## 架构

```
frontend (React + Vite, port 5173)
    │  POST /api/query/stream (SSE)
    ▼
backend (FastAPI, port 8000)
    │ 调用 task1/src/sql_agent 的 build_graph + astream
    ▼
task1 SQL Agent (LangGraph StateGraph)
    │ 选表 → 生成 SQL → 校验 → 执行 → 汇总
    ▼
Chinook SQLite 数据库 (只读)
```

## 快速开始

### 1. 安装 task1 依赖

```bash
cd task1
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. 安装 backend 依赖

```bash
cd task2/backend
pip install -r requirements.txt
```

### 3. 配置 API Key

```bash
export DEEPSEEK_API_KEY=your_api_key
# 可选：自定义 base URL
# export DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

### 4. 启动 backend

```bash
cd task2/backend
python server.py
# 或: uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

### 5. 启动 frontend

```bash
cd task2/frontend
npm install
npm run dev
```

### 6. 打开浏览器

访问 `http://localhost:5173`

## 项目结构

```
task2/
├── backend/
│   ├── server.py          # FastAPI 服务器：/api/health, /api/query, /api/query/stream
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx       # React 入口
│       ├── App.jsx        # 主组件：聊天界面 + 工作流步骤展示
│       ├── api.js         # API 请求封装（健康检查、同步/流式查询）
│       └── index.css      # 全局样式（暗色主题）
└── README.md
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 + API key 状态 |
| POST | `/api/query` | 同步查询（等待完整结果） |
| POST | `/api/query/stream` | SSE 流式查询（实时推送每个工作流步骤） |

### 同步查询请求/响应

```json
// POST /api/query
{ "question": "每位客户的总消费金额是多少？" }

// 响应
{
  "answer": {
    "answer": "共有 59 位客户...",
    "evidence": ["row_count=59"],
    "caveats": []
  },
  "stages": [
    { "node": "table_select", "stage": "table_select", "data": { "selection": { "tables": ["customers", "invoices"], ... } } },
    { "node": "execute", "stage": "execute", "data": { "sql": "SELECT ...", "execution": { "columns": [...], "row_count": 59 } } },
    ...
  ]
}
```

### 流式查询 (SSE)

```
event: stage
data: {"type":"stage","stage":"table_select","data":{"node":"table_select","selection":{...}}}

event: stage
data: {"type":"stage","stage":"execute","data":{"node":"execute","sql":"...","execution":{...}}}

event: complete
data: {"type":"complete","stage":"done","data":{}}
```

## 工作流步骤展示

前端实时展示每个工作流步骤：

1. 🔍 选择数据表 — 显示选中的表名和理由
2. ✅ 校验表选择 — 表名合法性和连通性检查
3. 🧠 生成 SQL — 显示生成的 SQL 语句
4. 🔒 校验 SQL — 安全检查 + EXPLAIN 编译校验
5. ⚡ 执行查询 — 返回行数和执行结果预览
6. 📝 汇总答案 — 中文自然语言答案
7. 🔧 修复 SQL（如有） — 重试次数追踪

## 前端特性

- **暗色主题**：护眼、专业
- **流式展示**：通过 SSE 实时推送工作流进度
- **示例问题**：侧边栏提供 6 个示例问题，点击即可查询
- **表清单**：显示 Chinook 数据库的 11 张业务表
- **答案详情**：可展开查看支撑证据和注意事项
- **工作流步骤**：可展开查看每个步骤的详细结果
- **连接状态**：实时显示后端连接和 API Key 配置状态
