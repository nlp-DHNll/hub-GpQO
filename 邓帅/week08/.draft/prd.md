# 深度研究助手 — 产品需求文档（PRD）

- 版本：v0.3（2026-09-09）
- 状态：设计已评审确认（含 grilling 评审修订：交付形态升级为完整前后端工程、任务生命周期补全），待实现
- 变更记录：v0.2 → v0.3 演示页改为 Vue3 完整前端；新增 checkpoint/取消/惰性恢复/quote 佐证等决策

## 1. 业务背景

市场 / 产品同学经常要对一个主题做调研（竞品分析、行业趋势、技术选型、政策解读）。人工搜索几十个网页、整理资料、写报告，一个主题动辄 2~3 小时，还容易漏信息、来源不可追溯。希望有一个工具能自动完成**深度研究**：输入一个主题，自动检索、阅读、迭代、综合，最终产出一份带来源引用的研究报告。

## 2. 产品定位

「深度研究助手」——输入一个研究主题，输出：

1. 一份**结构化研究报告**（摘要、分节正文、关键结论、遗留问题）
2. **来源列表**（每条结论关联 URL / 标题 / 来源，可追溯）
3. **研究过程记录**（检索了哪些关键词、读了哪些页面、迭代了几轮）
4. **置信度说明**（结论的可靠程度、信息截止时间、无来源结论标注为「模型推断」）

**交付形态**：FastAPI 后端 + **Vue 3 / Vite / Element Plus 完整前端工程**。提交完整前后端代码 + README。无数据库，报告文件持久化。

## 3. 核心流程

区别于一次性问答，研究是一个**由 LLM 自主迭代、带硬上限收敛**的循环：

```
plan（拆子问题）
  → search（多关键词检索）
  → read（抓取正文 + 逐页抽取要点，带原文佐证）
  → reflect（审视信息缺口）
       ├─ 信息不足 → 生成新查询，回 search（LLM 自主决定）
       └─ 信息充分 / 达到硬上限 / 用户取消 → 终止
  → synthesize（综合生成报告）→ save（落盘）
```

## 4. 功能需求

### 4.1 研究循环

| 节点 | 行为 |
|---|---|
| plan | LLM 将主题拆解为 3~6 个子问题（结构化输出） |
| search | 对每条待检索 query 调用 Bocha web-search（count=10，summary=true），结果跨轮按 URL 去重 |
| read | LLM 从本轮搜索结果挑选 ≤6 条高价值 URL → 并发抓取网页正文（trafilatura）→ 逐页 LLM 抽取要点，**每条要点 = {point, quote, url}**，quote 为 ≤50 字原文摘录佐证 → 写入 findings 与 sources |
| reflect | LLM 对照子问题审视已有 findings，输出 `{sufficient, gaps, new_queries}`（new_queries ≤4） |
| synthesize | 基于 findings 生成结构化报告，目录参考子问题但**按内容自由重组**；报告语言跟随主题语言（引用原文保留原语言） |
| save | 渲染 `report.md` + `process.json` 到 `reports/{task_id}/` |

### 4.2 迭代终止条件（任一满足即进 synthesize）

- reflect 判定信息充分（`sufficient=true`）
- 迭代轮数达到硬上限（默认 5 轮）
- 累计搜索次数达到预算（默认 30 次）

### 4.3 引用与置信度规则（防编造）

- 抽取要点强制带 quote（原文摘录）→ synthesize 阶段**只有能对应 quote 的结论才带 [n] 角标**，对不上的论断统一标注「（模型推断）」
- 报告头部标注「信息最新截至」= 所有来源中最新的发布日期（来源无日期时标注为检索日期）

### 4.4 任务生命周期

- **取消**：`DELETE /api/research/{task_id}` 取消在跑任务（asyncio 取消）；取消后 checkpoint 标记 aborted，**不生成**不完整报告
- **容错**：langgraph 文件 checkpoint（SQLite saver），每轮状态落盘
- **惰性恢复**：服务重启后不主动扫描；请求（SSE/查询）命中未完成任务时，从 checkpoint 断点续跑；维护任务状态索引以发现未完成任务
- **SSE 断线**：事件同步追加内存 buffer，SSE 带 Last-Event-ID 重放，前端自动重连

### 4.5 默认参数（config 可调）

| 参数 | 默认值 |
|---|---|
| MAX_ROUNDS | 5 |
| SEARCH_BUDGET（累计搜索次数） | 30 |
| 每轮新增查询上限 | 4 |
| 每轮阅读页面上限 | 6 |
| 单任务内部并发（抓取/LLM 抽取） | 3 |
| 单页正文截断 | ~8k tokens |
| 网页抓取超时 | 10s |

## 5. 系统设计

### 5.1 架构与目录

```
week08/
├── .draft/prd.md
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI 入口：API + 托管 frontend/dist（build 后）
│   │   ├── config.py           # pydantic-settings 读 .env
│   │   ├── llm.py              # langchain-openai 客户端（全节点用 BASE_MODEL）
│   │   ├── graph/
│   │   │   ├── state.py        # ResearchState（= 过程记录数据源）
│   │   │   ├── nodes.py        # plan / search / read / reflect / synthesize
│   │   │   └── builder.py      # StateGraph 组装：条件边 + 硬上限 + SqliteSaver
│   │   ├── tools/
│   │   │   ├── bocha.py        # Bocha web-search 封装（httpx）
│   │   │   └── fetcher.py      # 网页抓取（httpx + trafilatura 正文提取）
│   │   ├── report.py           # 报告渲染（md）+ 过程记录（json）落盘
│   │   └── api/routes.py       # 研究接口 + SSE + 取消 + 报告查询
│   └── tests/                  # pytest：节点单测 + mock 搜索的图冒烟
├── frontend/                   # Vue 3 + Vite + Element Plus
│   ├── src/
│   │   ├── views/              # 三视图：研究发起+进度 / 报告详情 / 历史列表
│   │   ├── components/         # 进度时间线、来源列表、过程记录面板等
│   │   ├── api/                # 接口封装（EventSource 消费 SSE）
│   │   └── router/
│   └── vite.config.ts          # dev 模式 proxy /api → localhost:8000
├── reports/                    # 每个研究任务一个子目录
└── README.md                   # 运行方式（双模式）+ 架构说明 + 演示截图位
```

**运行形态（双模式）**：
- 开发：`pnpm dev`（vite，proxy /api 到 FastAPI）+ `uvicorn` 两进程
- 演示/交付：`pnpm build` 出 dist → FastAPI 托管 dist，单进程 `uvicorn` 一条命令跑

**编排选型**：LangGraph `StateGraph` 手写研究图。理由：循环与硬上限是条件边的一等公民；共享状态天然就是「研究过程记录」；checkpoint（SqliteSaver）开箱支持断点续跑。

### 5.2 研究状态（ResearchState）

`topic`、`plan`（子问题列表）、`rounds`（每轮的 queries / 搜索结果 / 已读 URL / 要点）、`sources`（URL → 标题 / 摘要 / 被引用次数）、`iteration`、`pending_queries`、`sufficient`、`report_md`。

### 5.3 持久化格式

**`reports/{task_id}/report.md`**（覆盖输出物 1、2、4）：

```markdown
# {主题} 研究报告
> 生成时间 | 迭代 k 轮 | 引用 n 个来源 | 信息最新截至 {日期}
## 摘要
## 分节正文（目录按内容组织，结论带 [1][2] 角标）
## 关键结论
## 遗留问题
## 来源列表（[n] URL / 标题 / 摘要）
## 置信度说明（引用结论 vs「模型推断」+ 信息时效）
```

**`reports/{task_id}/process.json`**（输出物 3）：`{task_id, topic, created_at, plan, rounds[], stats（搜索次数 / 阅读页数 / 轮数）, model, status}`。

### 5.4 API 设计

| 接口 | 说明 |
|---|---|
| `POST /api/research` | `{topic}` → 启动研究（后台执行），返回 `{task_id}` |
| `GET /api/research/{task_id}/events` | SSE：轮次进度、检索 / 阅读事件、最终报告（Last-Event-ID 重放） |
| `DELETE /api/research/{task_id}` | 取消在跑任务（标记 aborted，不出报告） |
| `GET /api/reports` | 历史报告列表 |
| `GET /api/reports/{task_id}` | 报告 + 过程记录 |

### 5.5 前端（Vue 3 + Vite + Element Plus）

三视图（vue-router）：
1. **研究发起 + 实时进度**：主题表单 → 进度时间线（SSE 实时渲染「第 k 轮 / 正在检索『xxx』/ 已阅读 n 页 / 反思：还缺 xx」）
2. **报告详情**：markdown-it 渲染报告 + 来源列表 + 过程记录折叠面板
3. **历史列表**：报告表格，点击进入详情

## 6. 错误处理与降级

- Bocha 调用失败：重试 1 次，仍失败则该查询记为失败、流程继续
- 网页抓取失败（超时 / 非 HTML）：跳过抓取，**用搜索摘要兜底**进 findings（此来源要点标记「基于摘要」）
- LLM 结构化输出解析失败：重试 1 次
- 任何节点异常：不中断任务，带已有 findings 进 synthesize 出「不完整报告」（显式标注）

## 7. 配置管理

- LLM：复用项目根 `.env` 的 `API_KEY` / `BASE_URL` / `BASE_MODEL`（OpenAI 兼容接口；全节点统一用 BASE_MODEL，当前为 deepseek-v4-flash）
- 搜索：`BOCHA_API_KEY` 在项目根 `.env`，**密钥不写入代码与文档**
- 依赖：后端统一在 py312 conda 环境运行，允许按需安装（trafilatura、langgraph-checkpoint-sqlite），不维护 requirements.txt；前端 pnpm 管理依赖

## 8. 技术栈

- 后端：python + langchain（langchain-openai）+ langgraph（StateGraph + SqliteSaver）+ fastapi + httpx + trafilatura + sse-starlette
- 前端：Vue 3（`<script setup>` + TypeScript）+ Vite + Element Plus + vue-router + markdown-it（构建产物由 FastAPI 托管；API 响应与 SSE 事件定义 TS 类型，对应后端 schema）

## 9. 非目标（明确不做）

- 多用户 / 鉴权 / 权限
- 同时在跑任务数限制（不设限；单任务内部并发 3 已约束资源）
- 重启后自动扫描续跑（仅惰性恢复）
- 取消任务时生成不完整报告（只标记 aborted）
- 报告质量自动评估 / 打分

## 10. 验收标准

1. 三个测试主题跑通：竞品分析（如「国产新能源车企智驾方案对比」）、行业趋势、技术选型
2. 报告包含 PRD 四要素；带角标结论均可溯源（quote 佐证）；无来源结论有「模型推断」标注
3. 人工评审三份报告并**记录可溯源率**（带角标结论占比），不设硬阈值，供复盘
4. 前端完整走通：发起研究 → 实时进度 → 报告详情 → 历史回看；SSE 断线重连正常
5. 生命周期验证：取消生效（标记 aborted 不出报告）；kill 进程后重启，请求未完成任务可从断点续跑
6. `pytest` 通过（节点单测 + mock 搜索的图冒烟测试）
7. 硬上限生效：构造持续 insufficient 的场景，5 轮后强制收敛

## 附录 A：搜索工具参考

Bocha AI Web Search API 文档：https://bocha-ai.feishu.cn/wiki/RXEOw02rFiwzGSkd9mUcqoeAnNK

请求格式（密钥从 `.env` 读取）：

```
curl -X POST "https://api.bocha.cn/v1/web-search" \
  -H "Authorization: Bearer ${BOCHA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"query":"天空为什么是蓝色的？","summary":true,"count":10}'
```
