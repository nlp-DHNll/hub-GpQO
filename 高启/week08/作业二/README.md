# 综合案例 02 · 深度研究助手

**业务背景**：市场 / 产品同学经常要对一个主题做调研（竞品分析、行业趋势、技术选型、政策解读）。人工搜索几十个网页、整理资料、写报告，一个主题动辄 2~3 小时，还容易漏信息、来源不可追溯。希望有一个工具能自动完成**深度研究**：输入一个主题，自动检索、阅读、迭代、综合，最终产出一份带来源引用的研究报告。

**产品定位**：「深度研究助手」——输入一个研究主题，输出：

1. 一份**结构化研究报告**（摘要、分节正文、关键结论、遗留问题）
2. **来源列表**（每条结论关联 URL / 标题 / 来源，可追溯）
3. **研究过程记录**（检索了哪些关键词、读了哪些页面、迭代了几轮）
4. **置信度说明**（结论的可靠程度、信息截止时间、无来源结论标注为"模型推断"）

**核心流程**（区别于一次性问答）：规划（拆子问题）→ 多轮检索 → 阅读抽取 → 判断是否需要补检 → 综合生成报告。

# 搜索工具

https://bocha-ai.feishu.cn/wiki/RXEOw02rFiwzGSkd9mUcqoeAnNK

```
curl -X POST "https://api.bocha.cn/v1/web-search" \
  -H "Authorization: Bearer sk-3d2293ad83aa4823a7c7ce8dd5ff8c72" \
  -H "Content-Type: application/json" \
  -d '{"query":"天空为什么是蓝色的？","summary":true,"count":10}'
```

# 前端实现方案

后端已实现（FastAPI + OpenAI Agents SDK），前端为 Next.js，采用「客户端直连 + 轮询」模式对接后端接口。

## 技术栈

| 项 | 选择 |
|---|---|
| 框架 | Next.js 14（App Router）+ TypeScript |
| 样式 | Tailwind CSS |
| 数据请求 | 客户端 `fetch` + `setInterval` 轮询 |
| 后端地址 | 环境变量 `NEXT_PUBLIC_API_BASE`（默认 `http://localhost:8000`） |
| 状态管理 | React 本地 state + 自定义 hook |

## 目录结构

```
frontend/
├── package.json / tsconfig.json / next.config.mjs / tailwind.config.ts
├── .env.local              # NEXT_PUBLIC_API_BASE
├── app/
│   ├── layout.tsx          # 全局布局 + 字体 + 主题
│   ├── page.tsx            # 首页：输入框 + 历史列表
│   ├── globals.css
│   └── research/[id]/page.tsx   # 结果页（进行中 + 完成态共用）
├── components/
│   ├── ResearchForm.tsx        # 主题输入框 + 提交
│   ├── HistoryList.tsx         # 历史研究列表
│   ├── StatusBadge.tsx         # pending/running/completed/failed 徽章
│   ├── ProgressBar.tsx         # 顶部进度条 + 当前步骤文案
│   ├── ReportView.tsx          # 标题/摘要/正文分节/关键结论/遗留问题
│   ├── ConfidenceCard.tsx      # 置信度紧凑卡片
│   ├── SourcesList.tsx         # 来源列表（自适应折叠）
│   ├── ProcessTimeline.tsx     # 研究过程时间线（折叠）
│   └── ConclusionItem.tsx      # 结论项（来源点跳转 + 模型推断标注）
├── lib/
│   ├── api.ts              # fetch 封装（POST/GET/list）
│   ├── types.ts            # 前端 TS 类型（对齐 models.py 字段）
│   └── useResearchPolling.ts   # 轮询 hook
```

## 路由与页面

### 首页 `/`
- 研究表单：`textarea` 输入主题 + 提交，`POST /api/research` 拿到 `research_id` 后跳转结果页。
- 历史研究列表：`GET /api/research`，每项显示 `topic` + 状态徽章 + 时间，点击跳转。

### 结果页 `/research/[id]`（进行中 + 完成态共用）

靠 `status` 字段驱动单一状态机：

| status | 顶部 | 正文区 |
|---|---|---|
| `pending/running` | 进度条 + 当前步骤文案 | 实时渲染已累积 `draft` 段落（逐段出现） |
| `completed` | 进度条消失，显示置信度卡片 | 完整 `report` 渲染 |
| `failed` | 错误提示（`error` 字段） | 保留已累积的中间结果 |

## 轮询策略（`useResearchPolling`）

- 进入结果页立即 `GET` 一次，然后 `setInterval` 1.5s 轮询。
- 读到 `completed` / `failed` 即停止轮询。
- 用 `updated_at` 去重（避免重复 setState）。
- 组件卸载 / 路由离开时清理定时器。
- 进度条不是简单百分比，而是阶段进度：根据 `process.steps` 数量 + `iterations` 映射阶段文案（规划 → 检索 → 总结 → 判断 → 报告）。

## 四类产物的自适应布局

| 产物 | 内容量 | 策略 |
|---|---|---|
| 置信度 | 恒定少 | 顶部固定小卡片：等级徽章 + 信息截止时间 + note |
| 摘要/关键结论/遗留问题 | 少~中 | 正文区顶部平铺 |
| 正文分节 | 中~多 | 主体区纵向滚动，分节标题锚点导航 |
| 来源列表 | 可多 | ≤5 条内联平铺；>5 条折叠为「查看全部 N 个来源」展开面板 |
| 研究过程 steps | 可多 | 折叠时间线，默认收起，点击展开 |

## 交互细节

- 浅色主题、低饱和主色、充足留白；状态用色区分（running 主色、completed 绿色、failed 红色）。
- 结论可追溯：关键结论下方展示来源链接（可点跳转），`is_model_inference=true` 标注「模型推断」。
- 正文分节锚点导航，长报告可跳转。
- `draft` 段落逐段淡入；进度条下显示当前步骤细粒度文案（复用 `steps[].detail`）。
- 空态 / 错误态都有友好文案，不白屏。

## 接口契约（对接后端）

前端从 `report`（结构化 JSON）渲染，**不使用 `report_html`**。

- 端点：`GET /health`、`POST /api/research`（202 返回 `research_id`）、`GET /api/research/{id}`、`GET /api/research`。
- 状态机：`pending → running → completed / failed`。
- 响应体 `ResearchRecord` 关键字段：`research_id`、`topic`、`status`、`report`（title/summary/sections/key_conclusions/open_questions）、`sources`、`draft`、`process`（plan/search_queries/reviewed_urls/iterations/steps）、`confidence`（overall/info_cutoff/notes）。

## 实现顺序

1. 初始化 `frontend/`（package.json、tsconfig、tailwind、next.config）。
2. `lib/types.ts` + `lib/api.ts`（对齐 models.py 字段）。
3. `useResearchPolling` hook。
4. 首页（表单 + 历史列表）。
5. 结果页 + 各展示组件（进度条 → 报告 → 来源 → 过程 → 置信度）。
6. 样式打磨（清新主题、响应式）。
7. 联调验证（起后端 + 前端，跑一次真实研究）。

# 本地运行

## 前提

- 后端依赖：`pip install -r requirements.txt`（首次一次即可）。
- 前端依赖：`cd frontend && npm install`（首次一次即可）。
- 项目根目录 `.env` 需含有效的 `OPENAI_API_KEY`（DeepSeek）与 `BOCHA_API_KEY`。
- 后端启动时 `backend/config.py` 会自动 `load_dotenv` 加载根目录 `.env`，**无需手动 `source`**。

## 启动后端

> 必须在项目根目录（含 `backend/` 与 `.env` 的那层）下启动。

**Windows（PowerShell / cmd）**：

```powershell
cd 综合案例-02
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
# python 命令不可用时，改用 py：
py -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

**Linux / macOS（或用 Git Bash）**：

```bash
cd 综合案例-02
bash start.sh
# 或等价直接启动：
python3 -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

> `start.sh` 是给 bash 的脚本，Windows 原生的 PowerShell / cmd 上会因 `source .env` 等语法报错，直接用上面的 `python -m uvicorn` 命令即可，效果等价。

启动成功标志：出现 `INFO: Uvicorn running on http://127.0.0.1:8000`，`curl http://127.0.0.1:8000/health` 返回 `{"status":"ok"}`。

## 启动前端

```bash
cd frontend
npm run dev
```

浏览器打开 `http://localhost:3000` 即可开始研究。

## 完整联调（两个终端）

```bash
# 终端 1：后端（项目根目录）
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000

# 终端 2：前端
cd frontend && npm run dev
```

## 常见问题

| 现象 | 原因 / 解决 |
|---|---|
| `No module named 'backend'` | 没在项目根目录启动，`cd` 到含 `backend/` 的那层 |
| `No module named 'agents'` 等 | 依赖未装，`pip install -r requirements.txt` |
| `python` 命令找不到 | 改用 `py`，或确认 Anaconda 已加入 PATH |
| `address already in use` | 端口被占，换 `--port 8001`（前端同步改 `.env.local` 的 `NEXT_PUBLIC_API_BASE`） |
| 研究返回 `401 Authentication Fails` | `.env` 里 `OPENAI_API_KEY` 失效，换有效 key |