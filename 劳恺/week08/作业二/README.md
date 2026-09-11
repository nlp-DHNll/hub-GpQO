# 综合案例 02 · 深度研究助手

> 输入一个研究主题，自动检索 → 阅读 → 迭代 → 综合，产出带来源引用的结构化研究报告。

---

## 1. 项目简介

### 1.1 业务背景
市场 / 产品同学经常需要对某个主题做调研（竞品分析、行业趋势、技术选型、政策解读）。
人工搜索几十个网页、整理资料、写报告，一个主题动辄 2~3 小时，还容易漏信息、来源不可追溯。

### 1.2 产品定位
「深度研究助手」——输入一个研究主题，输出：

| 输出物       | 说明                                                                 |
| ------------ | -------------------------------------------------------------------- |
| 结构化报告   | 摘要、分节正文、关键结论、遗留问题（5 节 Markdown 模板）             |
| 来源列表     | 每条结论关联 URL / 标题，可追溯                                       |
| 研究过程记录 | 检索了哪些关键词、读了哪些页面、迭代了几轮                            |
| 置信度说明   | 结论可靠程度、信息截止时间、无来源结论标注为"模型推断"               |

### 1.3 核心流程
区别于一次性问答：**规划（拆子问题）→ 多轮检索 → 阅读抽取 → 判断缺口 → 综合生成报告**。

---

## 2. 技术栈

| 层        | 选型                                          |
| --------- | --------------------------------------------- |
| 语言      | Python 3.10+                                  |
| Web 框架  | FastAPI                                       |
| LLM 编排  | LangChain（自写主循环，仅用其 ChatModel）     |
| LLM 模型  | DeepSeek-V3 / R1                              |
| 搜索引擎  | 博查 AI（Bocha）Web Search（仅使用 summary）  |
| 配置      | python-dotenv + .env                          |
| 任务状态  | 内存 dict + JSON 文件落盘                     |

---

## 3. 架构

```
┌──────────────────────────────────────────────────────────────┐
│                     FastAPI (异步任务)                       │
│  POST /research  ──▶ 入队 ──▶ 后台 Worker                    │
│  GET  /research/{id}  ◀── 查状态/进度/结果                   │
└─────────────────────────────┬────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│              研究主循环（app/core/researcher.py）             │
│                                                              │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │
│  │ Planner │──▶│ Search  │──▶│ Extract │──▶│ Judge   │  │
│  │ 拆子问题│    │ 调用Bocha│    │ 抽取要点│    │ 是否补检│  │
│  └─────────┘    └─────────┘    └─────────┘    └────┬────┘  │
│       ▲                                              │       │
│       └──────────────── 补检（如需） ─────────────────┘       │
│                              │                               │
│                              ▼                               │
│                       ┌───────────┐                          │
│                       │ Synthesize│                          │
│                       │  生成报告  │                          │
│                       └───────────┘                          │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
            ┌─────────────────────────────┐
            │  data/ 目录（JSON 落盘）     │
            │  ├─ tasks/{task_id}.json   │  任务状态 + 过程
            │  └─ reports/{task_id}.md   │  最终报告
            └─────────────────────────────┘
```

---

## 4. 研究流程（快速深度）

| 步骤     | 动作                                                                                |
| -------- | ----------------------------------------------------------------------------------- |
| 规划     | LLM 把主题拆成 **3 个子问题**，覆盖不同维度                                         |
| 第 1 轮  | 对 3 个子问题**并行检索**，每子问题取 **5 条**结果，读取 Bocha `summary` 字段       |
| 第 2 轮  | LLM 评估已有内容 → 找出信息缺口 → 生成补充 query → 再搜一轮                        |
| 抽取     | 每条结果直接用 `summary` 喂给 LLM 抽取关键事实                                      |
| 综合     | 固定 5 节模板生成 Markdown 报告 + 脚注引用 + 置信度标签                              |
| 降级     | Bocha / LLM 失败自动**重试 3 次**（指数退避 1s/2s/4s）；整轮失败则跳过并标注"信息缺失" |

> ⚙️ 深度参数可在 API 请求中按次覆盖（`max_rounds`、`num_subquestions`），默认值见 §7。

---

## 5. 报告结构（5 节固定模板）

```markdown
# {主题} · 深度研究报告

> 生成时间：YYYY-MM-DD HH:MM　|　模型：DeepSeek-V3　|　检索轮数：2

## 摘要
（150~250 字，列出 3 条最关键发现）

## 背景 / 现状
…

## 关键发现
1. ……[1][2]
2. ……[3]
3. ……[4][5]

## 风险 / 争议
…

## 结论与遗留问题
…

---

## 来源列表
[1] 标题 — URL
[2] 标题 — URL
…

## 置信度说明
- 🟢 高：≥2 个独立来源支持
- 🟡 中：1 个权威来源支持
- 🔴 低：仅二手来源或来源不权威
- ⚪ 模型推断：LLM 基于常识推断，无来源
```

**置信度标签**示例：`🟢 高（2 个来源）` / `⚪ 模型推断`

---

## 6. 目录结构

```
deep-research/
├── app/
│   ├── api/
│   │   └── routes.py          # FastAPI 路由（POST/GET /research）
│   ├── core/
│   │   ├── researcher.py      # 研究主循环（核心状态机）
│   │   └── task_store.py      # 任务状态管理（内存 dict + JSON 落盘）
│   ├── llm/
│   │   └── deepseek.py        # LangChain + DeepSeek 封装
│   ├── search/
│   │   └── bocha.py           # 博查 AI 客户端
│   ├── report/
│   │   ├── templates.py       # 5 节报告 prompt 模板
│   │   └── renderer.py        # Markdown 渲染 + 脚注/置信度处理
│   └── models.py              # Pydantic 数据模型
├── data/
│   ├── tasks/                 # {task_id}.json 任务状态
│   └── reports/               # {task_id}.md 最终报告
├── main.py                    # uvicorn 启动入口
├── .env.example               # 环境变量模板
├── requirements.txt
└── README.md
```

---

## 7. 配置说明（.env）

复制 `.env.example` 为 `.env`，填入真实 key：

```ini
# 博查 AI
BOCHA_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
BOCHA_BASE_URL=https://api.bocha.cn/v1/web-search

# DeepSeek
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

# 服务
HOST=0.0.0.0
PORT=8000

# 研究深度默认值
DEFAULT_MAX_ROUNDS=2
DEFAULT_NUM_SUBQUESTIONS=3
DEFAULT_RESULTS_PER_QUERY=5

# 存储
DATA_DIR=./data
```

---

## 8. 快速开始

### 8.1 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 8.2 启动服务

```bash
cp .env.example .env
# 编辑 .env，填入 BOCHA_API_KEY 和 DEEPSEEK_API_KEY
python main.py
```

服务起在 `http://localhost:8000`，FastAPI 自动文档在 `http://localhost:8000/docs`。

---

## 9. API 示例

### 9.1 提交研究任务

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "2025 年中国新能源汽车行业竞争格局",
    "max_rounds": 2
  }'
```

**响应：**
```json
{
  "task_id": "f7a3c8e1-2b4d-4e9f-a1c5-3d8e9f0b1a2c",
  "status": "queued",
  "created_at": "2026-09-08 14:32:11"
}
```

### 9.2 轮询任务状态

```bash
curl http://localhost:8000/research/f7a3c8e1-2b4d-4e9f-a1c5-3d8e9f0b1a2c
```

**运行中：**
```json
{
  "task_id": "f7a3c8e1-...",
  "status": "running",
  "progress": "第 1 轮检索中 (2/3 子问题已完成)",
  "topic": "..."
}
```

**完成：**
```json
{
  "task_id": "f7a3c8e1-...",
  "status": "completed",
  "topic": "...",
  "report_markdown": "# ...",
  "sources": [
    {"id": 1, "title": "...", "url": "..."},
    ...
  ],
  "process": {
    "subquestions": ["...", "...", "..."],
    "rounds": [
      {"round": 1, "queries": ["..."], "results_count": 15},
      {"round": 2, "queries": ["..."], "results_count": 8}
    ],
    "duration_seconds": 78,
    "tokens_used": 12450
  },
  "created_at": "...",
  "finished_at": "..."
}
```

### 9.3 列出最近任务（可选）

```bash
curl http://localhost:8000/researches?limit=10
```

---

## 10. 报告示例（节选）

> 完整示例在 `data/reports/{task_id}.md` 中实际生成。

```markdown
# 2025 年中国新能源汽车行业竞争格局 · 深度研究报告

> 生成时间：2026-09-08 14:35:09　|　模型：DeepSeek-V3　|　检索轮数：2

## 摘要
2025 年中国新能源汽车市场 CR5 集中度进一步提升至约 68%，比亚迪以
约 32% 的市场份额领跑 🟢 高。价格战进入白热化阶段，头部车企通过
供应链垂直整合维持毛利 🟡 中。新势力中理想 / 鸿蒙智行 / 小鹏
形成第二梯队，合计份额约 22% 🟡 中。

## 关键发现
1. 比亚迪通过自研三电系统与芯片，将单车成本压低约 15%~20%，
   形成显著价格优势 [1][2]。 🟢 高
2. 特斯拉中国份额从 2023 年的 7.6% 下滑至 2025H1 的 4.2%，
   主因本土车型迭代更快 [3]。 🟡 中
3. ……

## 来源列表
[1] 比亚迪 2025 半年报 — https://...
[2] 36 氪：比亚迪供应链拆解 — https://...
[3] 乘联会 2025H1 数据 — https://...
```

---

## 11. 鲁棒性

| 故障                | 行为                                          |
| ------------------- | --------------------------------------------- |
| Bocha 搜索超时      | 自动重试 3 次（1s / 2s / 4s 指数退避）         |
| Bocha 整轮失败      | 跳过该轮，报告标注"第 N 轮信息缺失"           |
| DeepSeek 调用超时   | 自动重试 3 次                                  |
| DeepSeek 整轮失败   | 任务置 `failed`，返回错误信息给客户端          |
| Bocha 无结果        | LLM 改写 query 再试一次，仍无结果则跳过        |

---

## 12. 明确不做（v1 范围）

- Docker / 云端部署
- 单元测试 / e2e 测试
- LangSmith 集成
- 多 LLM 热切换
- WebSocket / SSE 流式响应（仅轮询）
- 用户认证 / 速率限制
- 历史任务检索（仅 `/researches` 列出最近 N 条）

---

## 13. 后续可扩展方向

- 接入 Jina Reader 抓全文，提升引用准确性
- LangGraph 重构主循环，支持可视化调试
- 增加报告导出 PDF / DOCX
- 引入 RAG：把历史报告作为知识库检索
- 多 LLM 评估器对报告打分
