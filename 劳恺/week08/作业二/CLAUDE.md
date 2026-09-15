# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 当前状态
- 仅 `README.md` 已完成，**代码尚未实现**。完整设计树（架构、流程、报告模板、API、目录结构、配置项）见 `README.md`。
- 实现顺序按 README §6 目录结构自底向上：先 `requirements.txt` + `.env.example` → `app/models.py` → 外部封装 → 核心循环 → 报告生成 → API 入口。

## 关键约定（来自设计树，编码时遵守）
- **LangChain 用法**：仅用其 `ChatModel` 抽象，**不**用 Agent / LangGraph；研究主循环是手写 Python（`app/core/researcher.py`）。
- **搜索数据**：Bocha Web Search 只取 `summary` 字段，**不**抓全文、不接 Jina Reader。
- **LLM 模型**：DeepSeek-V3 / R1（OpenAI 兼容接口），不接 Claude / GPT / 国产其他模型。
- **报告结构**：固定 5 节模板（摘要 / 背景现状 / 关键发现 / 风险争议 / 结论遗留），引用用脚注 `[n]`，置信度用 🟢🟡🔴⚪ 标签——**不**动态分节、不输出 PDF/HTML。
- **任务状态**：内存 dict + JSON 落盘到 `data/tasks/{task_id}.json`，报告落盘到 `data/reports/{task_id}.md`。**不**接 Redis / Celery。
- **API 形态**：FastAPI 异步任务 + 轮询（`POST /research` → `GET /research/{task_id}`），**不**做 SSE / WebSocket。
- **错误处理**：Bocha / DeepSeek 失败自动重试 3 次（指数退避 1s/2s/4s）；整轮失败跳过并标注信息缺失。**不**做完整降级链路。
- **测试**：v1 不写单元测试 / e2e。
- **配置**：所有 key / 参数走 `.env` + `python-dotenv`，**禁止**硬编码 API key。

## 实现时的最小起步命令
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # 填入 BOCHA_API_KEY 与 DEEPSEEK_API_KEY
python main.py                   # uvicorn 启动，监听 0.0.0.0:8000
```
FastAPI 自动文档：`http://localhost:8000/docs`。

## 改动 README 时的红线
- 不要破坏 §5 的 5 节报告模板和置信度标签体系——客户端可能依赖此结构。
- 不要把 `data/` 路径或 `.env` 变量名改了，除非同步更新 `app/core/task_store.py` 和 `app/core/researcher.py` 的引用。

## 后续若新增能力
任何对以下边界的扩展需先和用户确认（v1 明确不做）：
- 抓全文 / Jina Reader / 全文抽取
- Docker / 云端部署
- 单元测试 / e2e
- LangSmith 集成
- SSE / WebSocket
- 多 LLM 热切换
