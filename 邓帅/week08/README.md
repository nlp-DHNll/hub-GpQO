# 深度研究助手

输入一个研究主题,系统自动完成「拆解子问题 → 多轮检索与阅读 → 反思信息缺口 → 综合生成报告」的深度研究循环,产出**带来源引用、可溯源、带置信度说明**的结构化研究报告。

- 后端:Python + LangGraph(`StateGraph` 编排研究循环,`SqliteSaver` 每轮 checkpoint 落盘)+ FastAPI + Bocha 搜索 + trafilatura 正文提取
- 前端:Vue 3(`<script setup>` + TypeScript)+ Vite + Element Plus,构建产物由 FastAPI 托管

## 研究循环

```
plan(拆 3~6 个子问题)
  → search(Bocha web-search,count=10,跨轮按 URL 去重)
  → read(挑 ≤6 条高价值 URL → 并发抓取 → 逐页抽取要点:{point, quote≤50字原文摘录, url})
  → reflect(LLM 审视缺口:{sufficient, gaps, new_queries≤4})
       ├─ 信息不足 → 生成新查询回 search
       └─ 信息充分 / 5 轮硬上限 / 30 次搜索预算 → 终止
  → synthesize(综合报告,结论带 [n] 角标或「模型推断」标注)
  → save(reports/{task_id}/ 落盘 report.md + process.json)
```

**防编造机制**:抽取要点强制携带原文 quote 佐证;synthesize 只有能对应 quote 的结论才带 `[n]` 角标,对不上的论断统一标注「(模型推断)」;报告头部「信息最新截至」取所有来源最新发布日期。

## 运行方式

凭据在项目根 `.env`:`API_KEY` / `BASE_URL` / `BASE_MODEL`(OpenAI 兼容)+ `BOCHA_API_KEY`(Bocha 搜索)。密钥不写入代码与文档。

### 演示模式(推荐,单进程)

```bash
cd frontend && pnpm install && pnpm build   # 构建前端产物
cd ../backend
/opt/miniconda3/envs/py312/bin/python -m uvicorn app.main:app --port 8000
# 打开 http://localhost:8000
```

### 开发模式(双进程,前端热更新)

```bash
cd backend && /opt/miniconda3/envs/py312/bin/python -m uvicorn app.main:app --port 8000
cd frontend && pnpm dev                      # vite proxy /api → localhost:8000
# 打开 http://localhost:5173
```

### 测试

```bash
cd backend && /opt/miniconda3/envs/py312/bin/python -m pytest tests/ -q
# 工具层单测 + mock 搜索/LLM 的图冒烟(硬上限/预算/降级)+ API 层测试
```

## API

| 接口 | 说明 |
|---|---|
| `POST /api/research` | `{topic}` → 后台启动研究,返回 `{task_id}` |
| `GET /api/research/{task_id}/events` | SSE 实时进度(轮次/检索/阅读/反思/完成),支持 Last-Event-ID 重放 |
| `GET /api/research/{task_id}` | 任务状态查询 |
| `DELETE /api/research/{task_id}` | 取消在跑任务(标记 aborted,不生成报告) |
| `GET /api/reports` | 历史报告列表 |
| `GET /api/reports/{task_id}` | 报告 + 过程记录 |

## 任务生命周期

- **checkpoint**:LangGraph `SqliteSaver`(`reports/checkpoints.db`)每轮落盘
- **惰性恢复**:服务重启后不主动扫描;请求命中未完成任务时从 checkpoint 断点续跑
- **SSE**:事件同步入内存缓冲,断线重连带 Last-Event-ID 从断点重放
- **降级**:搜索失败重试、抓取失败用摘要兜底(标「基于摘要」)、LLM 解析失败重试、节点异常出显式标注的「不完整报告」

## 目录结构

```
week08/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 入口 + 托管 frontend/dist
│   │   ├── config.py        # pydantic-settings(.env + 研究参数)
│   │   ├── llm.py           # ChatOpenAI 客户端
│   │   ├── schemas.py       # 结构化输出模型(plan/read/select/reflect)
│   │   ├── report.py        # 报告渲染 + process.json + 任务状态落盘
│   │   ├── graph/           # state / nodes / builder(StateGraph + 条件边 + SqliteSaver)
│   │   ├── tools/           # bocha 搜索 / fetcher 抓取
│   │   └── api/routes.py    # 研究接口 + SSE + 取消 + 惰性恢复
│   └── tests/               # pytest
├── frontend/                # Vue 3 + Vite + Element Plus(三视图)
└── reports/                 # 每任务一个子目录(report.md / process.json / status.json)
```

## 输出物

每个任务在 `reports/{task_id}/` 下产出:

- **report.md**:摘要 / 分节正文(结论带 `[n]` 角标)/ 关键结论 / 遗留问题 / 来源列表 / 置信度说明
- **process.json**:检索了哪些关键词、读了哪些页面、迭代几轮、来源元数据与被引次数

## 演示截图

**研究发起与实时进度**(SSE 时间线:拆解子问题 → 检索 → 阅读 → 反思 → 迭代)

![进度](screenshots/progress.png)

**报告详情**(markdown 渲染 + 角标引用 + 来源列表 + 过程记录)

![报告](screenshots/report.png)

**历史列表**

![历史](screenshots/history.png)

**发起页**(已完成研究统计)

![首页](screenshots/home.png)
