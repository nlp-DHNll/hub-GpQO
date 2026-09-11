# CLAUDE.md

本文件用于指导 Claude Code（claude.ai/code）在本仓库中的工作方式。

## 项目概览

**深度研究助手**：输入一个研究主题，自动完成检索、阅读、迭代、综合，产出一份带来源引用的研究报告。`README.md` 是唯一规格来源，所有产品要求以此为准。

输入一个主题，输出四类产物：结构化报告（report）、来源列表（sources）、研究过程记录（process）、置信度说明（confidence）。

## 核心架构：研究循环（agentic loop，不是单次问答）

```
规划 → 多轮检索 → 阅读抽取 → 判断补检 → 综合生成报告
```

- **迭代是产品特性**：保留「判断补检」这一环，不能做成一次检索就出报告。
- **可追溯是硬要求**：每条结论要关联来源 URL/标题。
- **过程记录要落盘**：检索关键词、已读页面、迭代轮数都要记录。

## 多 Agent 分工（改动前先读）

- `agent/` 只含**角色 agent**（keyword / summary / judge / report），都是**无工具**的单次 LLM 调用，继承 `BaseAgent`。
- `engine.py` 的 `DeepResearch` 是**编排器（不是 agent）**：不做任何 LLM 调用，只做确定性控制流——规划 → 逐关键词 `web_search` → 总结并累积进 `draft` → 判断补检（最多 `MAX_ROUNDS` 轮）→ 收集来源 + 确定性计算置信度 → 报告。
- 每个 `.py` 文件末尾都要有 `if __name__ == "__main__":` 测试 demo。

## 技术栈与关键决策

- **Agent 基于 openai-agents SDK**：`set_default_openai_api("chat_completions")` + `set_tracing_disabled(True)`（在 `agent/base.py` 模块级）；模型 `deepseek-v4-flash`，指向 `https://api.deepseek.com/`。
- **DeepSeek 不支持 `output_type`**：提示词强制输出唯一 JSON，`parse_json` 用 pydantic + ```json 代码块正则兜底解析。
- **空输出自动重试**：DeepSeek 偶发返回 200 + 空 content，`BaseAgent._run` 重试 `LLM_RETRIES` 次。
- **所有 pydantic 模型都在 `backend/models.py`**：`agent/`、`templates/` 里不定义模型。
- **提示词与代码分离**：所有提示词在 `backend/templates/`，`BaseAgent._render` 用 Jinja2 渲染。
- **SummaryAgent 输出纯文字**：不走 JSON 解析，直接用 `_run` 拿原始输出。
- **运行方式**：POST 返回 202 + research_id，`asyncio.create_task` 后台执行，前端轮询 GET。

## 常用命令

```bash
pip install -r requirements.txt
bash start.sh                                  # 或 uvicorn backend.app:app --reload --port 8000

# 本地自检（无需网络/密钥）
python -m backend.config
python -m backend.models
python -m backend.storage
python -m backend.agent.base
python -m backend.agent

# 涉及网络/LLM 的端到端（需要 .env 密钥）
python -m backend.engine
python -m backend.research
```

## 编码约定

- 日志用标准库 `logging`，每个模块一个 `logger = logging.getLogger(__name__)`。
- 每个后端 `.py` 文件末尾写 `__main__` 测试 demo；`__init__.py` 只做导出。
- 涉及网络/LLM 的 demo 写好但不自动跑（需密钥），供人工端到端验证。
