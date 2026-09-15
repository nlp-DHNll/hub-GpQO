# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

深度研究助手：输入研究主题 → LangGraph 驱动「plan → search → read → reflect 迭代 → synthesize」研究循环 → 产出带 `[n]` 角标引用、可溯源、带置信度说明的研究报告。后端 Python（FastAPI + LangGraph），前端 Vue 3 + Vite + Element Plus。

父目录 `badou2026/CLAUDE.md` 的 LLM 调用规范与 py312 环境约定同样适用；本项目额外需要 `BOCHA_API_KEY`（Bocha 搜索）。

## 常用命令

```bash
# 后端（须在 backend/ 目录下运行，app 包按相对路径导入）
cd backend && /opt/miniconda3/envs/py312/bin/python -m uvicorn app.main:app --port 8000

# 前端（包管理器为 pnpm）
cd frontend && pnpm dev     # 开发模式 :5173，vite proxy 把 /api 转发到 :8000
cd frontend && pnpm build   # 构建产物 dist/ 由 FastAPI 托管（演示模式单进程 :8000）

# 测试（pytest.ini 已设 asyncio_mode=auto；搜索与 LLM 均为 mock，无需凭据）
cd backend && /opt/miniconda3/envs/py312/bin/python -m pytest tests/ -q
cd backend && /opt/miniconda3/envs/py312/bin/python -m pytest tests/test_graph.py -q              # 单文件
cd backend && /opt/miniconda3/envs/py312/bin/python -m pytest "tests/test_graph.py::test_xxx" -q  # 单测试
```

## 架构

请求主链路：`POST /api/research` 创建 task_id 并起 asyncio 后台协程驱动 LangGraph 图 → 节点内细粒度进度经 `get_stream_writer()` 发 custom 事件 → `routes.py` 的 TaskEntry 缓冲 → SSE `/events` 推给前端（Last-Event-ID 断线重放）。

### 研究图（backend/app/graph/）

- `state.py`：`ResearchState`（TypedDict）既是图状态也直接充当 process.json 的数据源。reducer 约定：`rounds` / `findings` / `search_count` 追加累加；`sources` / `seen_urls` dict 合并去重；`degraded` 布尔或（一旦置位不清除）；其余字段后写覆盖。
- `nodes.py`：五个节点全部返回**增量 dict**，由上述 reducer 合并；每个节点都有降级路径（异常不中断任务，置 `degraded`，最终产出标注「不完整报告」）。新增/修改节点必须遵守这两条约定。
- `builder.py`：`route_after_reflect` 是迭代收敛条件——sufficient / 轮数≥max_rounds / 搜索数≥search_budget / 无 pending_queries，任一满足即进 synthesize。

### 任务生命周期（backend/app/api/routes.py）

- 运行时状态索引是**进程内** `TASKS` dict；持久层是 `reports/{task_id}/status.json` + LangGraph checkpoint（`reports/checkpoints.db`）。
- 服务重启后**惰性恢复**：请求命中内存没有的 task_id 时按三级解析（`_resolve_task`）——内存 → status.json 已终结 → checkpoint 断点续跑。
- 状态机：running → completed / incomplete（降级完成）/ aborted / failed。
- checkpointer 在 FastAPI lifespan 中创建并挂到 `app.state`，API 层经 `_checkpointer(request)` 获取。

### 防编造机制（改动时不可破坏）

- read 节点每条要点强制为 `{point, quote≤50字原文摘录, url}`；正文抓取失败用搜索摘要兜底并标 `from_summary: true`。
- synthesize 生成的正文只有能对应 quote 的结论才带 `[n]` 角标，对不上的论断统一标「(模型推断)」。
- 报告头部「信息最新截至」、来源列表、置信度说明由 `report.py` **程序渲染**，LLM 只生成正文章节——调整报告版式改 report.py 的渲染逻辑，不要往 synthesize 的 prompt 里加这些内容。

### 配置（backend/app/config.py）

- `_find_env_files()` 收集 week08 向上整条目录链的所有 .env，**近的覆盖远的**：`邓帅/.env` 覆盖 `badou2026/.env`，缺失的键（如 BOCHA_API_KEY）从更靠根的 .env 补全。
- 研究参数（max_rounds=5、search_budget=30、max_read_per_round=6、concurrency=3 等）集中在 `Settings`，均可用 .env 覆盖。

## 约定

- 代码注释、LLM prompt、报告文案、提交信息均使用中文；密钥不写入代码与文档。
- `reports/` 是运行时产物（含 checkpoint 数据库），`作业一/`、`作业二/` 是作业截图，`.draft/prd.md` 是需求文档。
- 本仓库是多人作业提交仓库（上层 `邓帅/week01..week08`），不要改动其他同学与老师的文件，文件名不含空格或 `.` 等特殊符号。
