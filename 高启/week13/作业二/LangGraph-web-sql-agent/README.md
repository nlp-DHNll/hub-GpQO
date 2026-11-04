# LangGraph Web SQL Agent

基于 FastAPI、LangGraph、LangChain 和 SQLite 的自然语言查询网页。前端提交问题，后端运行 LangGraph 查询流程，并返回答案、SQL 和查询信息。

## 运行环境

- Python 3.10 或更新版本
- 一个兼容 OpenAI Chat Completions 的 API Key

## 安装和配置

在项目根目录创建 `.env`：

```env
OPENAI_API_KEY=你的 API Key
OPENAI_BASE_URL=https://api.deepseek.com
SQL_AGENT_MODEL=deepseek-flash
SQL_AGENT_SUMMARY_MODEL=deepseek-flash
```

安装项目依赖：

```powershell
python -m pip install -e .
```

## 启动网页

```powershell
python -m sql_agent_web.web
```

浏览器打开 <http://127.0.0.1:8000>。默认只监听本机地址。

也可以用安装后的命令启动：

```powershell
sql-agent-web
```

## API

`POST /api/query` 接收 JSON：

```json
{
  "question": "总共有多少张专辑？"
}
```

返回 `WorkflowOutput` JSON，包含答案、执行 SQL、表名、行数、修复次数、证据和提示。`GET /api/health` 返回服务状态和当前模型名；FastAPI 文档位于 `/docs`。

## 项目结构

```text
src/sql_agent_web/
├── web.py                 # FastAPI 服务和 API
├── graph_workflow.py      # LangGraph 查询工作流
├── agents/                # LangChain 结构化模型调用
├── db/                    # 数据库目录、SQL 校验、只读执行
└── web/
    ├── index.html         # 网页入口
    └── static/            # CSS 和浏览器端 JavaScript
```

数据库连接保持只读；SQL 由工作流校验后才执行。不要把真实 `.env` 文件提交到版本库。
