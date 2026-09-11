# 深度研究助手（Deep Research）· 需求与设计文档

> 版本 v0.1 · 本文档是唯一的需求/规格来源，实现以本文为准。

## 一、业务背景

市场 / 产品同学经常要对一个主题做调研（竞品分析、行业趋势、技术选型、政策解读）。人工做一次深度研究要搜索几十个网页、整理资料、写报告，一个主题动辄 2~3 小时，还容易漏信息、来源不可追溯。

## 二、产品定位

输入**一个研究主题**，自动完成检索 → 阅读 → 迭代 → 综合，输出**四类产物**：

| # | 产物 | 说明 |
|---|------|------|
| 1 | 结构化研究报告 | 标题、摘要、分节正文、关键结论、遗留问题 |
| 2 | 来源列表 | 每条结论关联 URL / 标题，**可追溯** |
| 3 | 研究过程记录 | 检索了哪些关键词、读了哪些页面、迭代了几轮 |
| 4 | 置信度说明 | 结论可靠程度、信息截止时间；无来源结论标注「模型推断」 |

## 三、核心流程（区别于一次性问答）

```
规划（拆子问题/关键词）
  → 多轮检索
  → 阅读抽取（综合成正文段落）
  → 判断是否需要补检（不足则回到检索）
  → 综合生成报告
```

**「判断补检」这一环是产品特性**：不能做成「搜一次就出报告」，要有明确的收敛判定。

## 四、技术方案

| 层面 | 选型 | 说明 |
|------|------|------|
| LLM | DeepSeek（`deepseek-v4-flash`，OpenAI 兼容接口） | 通过 openai-agents SDK 调用 |
| 搜索 | Bocha 网页搜索 API | `POST https://api.bocha.cn/v1/web-search` |
| 后端 | Python FastAPI | 提供研究发起 + 轮询接口 |
| 提示词 | Jinja2 模板 | 提示词与代码分离，每个 agent 一个模板 |
| 存储 | 本地 JSON 文件 | `backend/data/research/{id}.json` |

## 五、系统架构（多 Agent 分工）

关键设计：**角色 agent 只做单次 LLM 调用、不带工具；编排交给引擎的确定性控制流。**

```
DeepResearch 引擎（编排器，不做 LLM 调用，只做确定性控制流）
  ├── KeywordAgent  把主题拆成 3-5 个可检索关键词（规划）
  ├── SummaryAgent  把某关键词的搜索结果综合成一段报告正文
  ├── JudgeAgent    判断草稿是否足够，不足则给出新关键词（补检）
  ├── ReportAgent   生成报告元信息 + 渲染自包含 HTML
  └── web_search    直接调用 Bocha 搜索（普通 async 函数，不是工具）
```

```
backend/
├── app.py          # FastAPI：/health、POST /api/research、GET /api/research/{rid}、GET /api/research
├── config.py       # 从项目根 .env 读配置
├── models.py       # Pydantic：四类产物 + 中间结果 schema
├── tools.py        # web_search（Bocha）
├── engine.py       # ★ DeepResearch 研究引擎（编排器）
├── research.py     # 后台执行 + 中间结果逐步落盘
├── storage.py      # JSON 文件读写
├── agent/          # ★ 多 agent 包（只含角色 agent）
│   ├── base.py     #   BaseAgent 基类（LLM 调用 + JSON 解析）
│   ├── keyword.py  #   KeywordAgent
│   ├── summary.py  #   SummaryAgent
│   ├── judge.py    #   JudgeAgent
│   └── report.py   #   ReportAgent
└── templates/      # Jinja2 提示词模板（每个 agent 一个）
```

## 六、接口设计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/research` | 发起研究，`{"topic": "..."}` → `202` + `research_id`，后台异步执行 |
| GET | `/api/research/{rid}` | 按 id 查询状态/结果（前端轮询） |
| GET | `/api/research` | 研究列表 |

状态机：`pending → running → completed / failed`。

## 七、关键设计决策

1. **提示词与代码分离**：LLM 提示词全在 `templates/`，代码只负责渲染与调用。
2. **结构化输出兼容 DeepSeek**：DeepSeek 不支持 SDK 的 `output_type`，因此提示词强制输出唯一 JSON（```json 代码块包裹），代码侧用 `parse_json` 解析（pydantic 直接解析 + 代码块正则兜底）。
3. **空输出自动重试**：DeepSeek 偶发返回 `200` 但 `content` 为空，`BaseAgent` 对空输出重试 `LLM_RETRIES` 次。
4. **正文直接累积**：每个关键词检索结果的总结段落直接累积进报告草稿 `draft`，正文分节 = 草稿段落映射（heading=keyword、body=text），不让 LLM 重新组织正文。
5. **置信度确定性计算**：按来源数量分级（≥12 high / ≥5 medium / 其余 low），信息截止时间取来源最新日期。
6. **中间结果落盘**：每完成一轮通过 `on_progress` 回调写盘，轮询即可实时看到研究过程。

## 八、运行方式

```bash
pip install -r requirements.txt      # 安装依赖
cp .env.example .env                 # 配置密钥（或用课程提供的 .env）
bash start.sh                        # 启动后端（默认 :8000）

# 发起研究
curl -X POST http://127.0.0.1:8000/api/research \
  -H 'Content-Type: application/json' \
  -d '{"topic":"2026 年主流 Agent 框架对比"}'

# 轮询结果
curl http://127.0.0.1:8000/api/research/<research_id>
```

> **运行前注意**：`.env` 里的 `OPENAI_API_KEY`（DeepSeek）是课程提供的演示 key，若已失效请换成你自己的 key；`BOCHA_API_KEY` 同理。Bocha 搜索是实网调用、DeepSeek 是 LLM 调用，两者都需要有效密钥才能跑通完整研究流程。本地逻辑自检（`python -m backend.config/models/storage/agent.base/agent`）不依赖密钥，可直接跑。
