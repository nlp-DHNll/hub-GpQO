# 作业2：Skill 有确定性 Script vs 无 Script 的效果对比实验

> 实验日期：2026-11-25｜环境：Windows + Python 3.12 + CodeBuddy（web_search / web_fetch 工具）｜对比对象：`esg-monthly-report` 与 `esg-tender-intel` 两个 Skill

## 一、实验设计

### 1.1 控制变量

为公平比较，两组使用**完全相同的 4 条检索式**（见 `实验_无Script基线/compare_queries.txt`）：

1. `2026年11月 ESG 政策 标准 评级 最新动态`
2. `中国神华 ESG 2026年11月 可持续发展 最新动态`
3. `ESG 可持续发展 双碳 中标公告 2026 招标 中标金额`
4. `ESG 中标公告 2025 中标金额 万元 成交结果`

### 1.2 两组定义

| 组别 | 可用能力 | 交付物 |
|------|----------|--------|
| **A 组：无 Script** | 仅 Skill 的文字流程 + 语义检索工具 + Agent 人工阅读/摘要；禁止运行任何脚本 | `实验_无Script基线/案例一_无脚本基线.md`、`案例二_无脚本基线.md` |
| **B 组：有 Script** | 同一流程 + `search_web.py` / `summarize.py` / `aggregate_tenders.py` / `monitor_daily.py` / `validate_report.py` | `运行日志与中间数据/compare_search.json`、`compare_evidence.json`、`compare_stats.json`、`compare_tenders.csv`、`monitor_idempotency_check.md` |
| **C 组：混合（实际交付）** | B 组脚本做确定性环节 + 语义检索补证据 + Agent 写最终分析 | 两份终稿报告（均通过 validate_report.py，得分 100/100） |

### 1.3 指标定义

- 链接数：正则提取报告中唯一 `http(s)` URL 数；
- 明确日期数：`YYYY-MM-DD` 格式去重后计数（中文“11月24日”不计）；
- 数字主张数：匹配 `亿元/万元/%/项/家` 单位的数字出现次数；
- 金额可得率：能抽取到中标金额的记录数 ÷ 纳入记录数；
- 耗时：B 组用 PowerShell `Measure-Command` 实测；A 组检索耗时取工具返回的 responseTimeMs 之和，人工写作时间未精确计时。

## 二、执行记录

### 2.1 A 组（无 Script）

- 4 次语义检索：responseTimeMs 分别为 1290 / 1056 / 879 / 814 ms，合计约 **4.0 秒**；命中 8+8+8+10 = **34 条**结果。
- Agent 人工阅读并挑选：案例一保留约 10 条、案例二约 12 条；人工识别出 2 组重复（海南双碳平台在政府采购网与海南省发改委重复、邯郸 ESG 评价在中国政府采购网与河北省政府采购网重复），但**未留下去重日志**。
- 人工撰写两份基线简报，合计约 3,200 字符；金额单位混用（元 / 万元 / 亿元 / 万元每年），未做统一换算表；未计算金额分布、主题统计或供应商频次。

### 2.2 B 组（有 Script）

```powershell
# 1) 检索（26.64 秒）
python search_web.py --query-file compare_queries.txt --out compare_search.json --max 8 --engine auto --sleep 1.0 --reference-date 2026-11-25
# 2) 抽取式摘要（14.15 秒）
python summarize.py --input compare_search.json --out compare_evidence.json --limit 34 --fetch-limit 8
# 3) 招投标聚合（0.37 秒）
python aggregate_tenders.py --input compare_search.json --out-json compare_stats.json --out-csv compare_tenders.csv --out-md compare_stats.md
# 4) 每日监控幂等性：第二次以相同输入运行 → new=0
python monitor_daily.py --input case2_search.json --state monitor_state.json --out monitor_idempotency_check.md
```

运行结果要点：

- 检索：**34 条**唯一结果（10/10/4/10），其中 **15 条**推断出日期，`deduped=0`（本组 4 条检索式间无重复 URL）；
- 稳定性事件：3 次 360 搜索请求出现 `SSLError`，`--engine auto` 自动回退 Bing 后完成检索，失败与回退均写入 stderr 日志；纯 `so360` 模式在同一时段只拿到 11 条（2 条检索式失败），说明**高代码检索后端存在限流风险**；
- 聚合：34 条记录中 **0 条抽取到中标金额**（搜索摘要被截断、缺少“中标金额”字段），证明**纯规则抽取依赖输入文本质量**；
- 监控：同一输入重复运行新增 0 条，state 去重有效；
- 三阶段合计 **41.16 秒**，且每次运行产生可复现的 JSON/CSV 中间文件。

## 三、定量对比

| 指标 | A 组：无 Script | B 组：有 Script | C 组：混合（终稿） |
|------|-----------------|-----------------|-------------------|
| 检索工具耗时 | 约 4.0 秒（语义检索） | 41.16 秒（含回退重试与 8 次网页抓取） | 约 45 秒 + Agent 写作 |
| 检索式/命中 | 4 条 / 34 条 | 4 条 / 34 条（含 3 次失败回退） | 12 条 / 63 条（案例一）、57 条（案例二） |
| 去重 | 人工发现 2 组，无日志 | URL SHA1 自动去重，有 `deduped` 字段 | 自动去重 + Agent 复核项目编号 |
| 日期识别 | 靠人工阅读；中文日期未标准化 | 15/34 条自动推断 ISO 日期 | 24 / 37 个明确 ISO 日期 |
| 案例一报告字符数 | 1,448 | 无成稿（仅证据 JSON） | 9,729 |
| 案例二报告字符数 | 1,711 | 无成稿（仅统计表） | 9,750 |
| 唯一来源链接数 | 7 / 8 | JSON 中 34 条 URL | 28 / 38 |
| 明确 ISO 日期数 | 1 / 9 | 15（推断） | 24 / 37 |
| 数字主张数 | 1 / 3 | 0（金额抽取失败） | 24 / 52 |
| 金额可得率 | 8/8 人工读取（但单位混用） | 0/34 | 32/37（86.5%，语义检索补充后） |
| 结构化中间数据 | 无 | JSON + CSV + Markdown 统计表 | JSON + CSV + 校验报告 |
| 自动校验 | 无 | validate_report.py 可用 | 两份报告均 100 分通过 |
| 重复运行一致性 | 依赖上下文，不可保证 | 同一输入 → 同一输出（除实时网页） | 关键数字可回溯到 CSV |

## 四、定性分析

### 4.1 Script 明显更强的环节

1. **确定性与可复现**：检索式、命中数、去重数、评分权重全部落盘为 JSON；同样的输入可得到同样的中间结果。无 Script 模式下，“保留哪条、舍弃哪条”只存在于 Agent 的临时上下文中。
2. **机械性工作不漏**：日期推断、URL 哈希去重、单位换算（亿元×10000、元÷10000）、金额分箱、供应商频次、项目编号去重，这些规则任务脚本一次完成且不会疲劳遗漏；`monitor_daily.py` 第二次运行 `new=0` 证明增量推送可靠。
3. **上下文效率**：脚本输出是紧凑的 JSON/CSV，Agent 只需读取 top-N 结果；无 Script 模式要把 34 条长摘要全部塞进上下文， token 消耗更高且容易“中间遗忘”。
4. **质量闸门**：`validate_report.py` 把“章节齐全、来源≥12、时间窗日期≥3、无占位符、数字≥5”变成可执行的检查，避免交付前漏项。

### 4.2 Script 明显更弱的环节

1. **检索后端脆弱**：高代码只能直连公开搜索页，360 触发 SSL/限流，Bing 中文查询相关性差且返回无关结果（早期调试曾返回“高德地图”“昇菘 CEO 薪酬”等无关内容）。语义检索工具在本环境下相关性显著更高。
2. **摘要质量生硬**：抽取式 jieba TF-IDF 会选出标题句、表格数字行作为“关键句”；例如 ETF 申赎清单页面被选中的摘要是标题本身，甚至出现 `10010000.00%` 这类表格噪声。它适合做线索表，不适合直接成为报告表述。
3. **输入文本一变就失效**：B 组同样 4 条检索式，因 Bing 回退摘要截断，金额抽取从“人工可读 8/8”跌到“规则抽取 0/34”。规则脚本没有语义补全能力。
4. **无法做影响判断**：“获奖是否等于 ESG 绩效改善”“煤制气项目对 E 维度的双向影响”这类结论必须依赖领域推理，脚本只能提供事实字段。

### 4.3 结论：混合模式最优

- **最佳分工**：Script 负责采集日志、去重、日期/单位归一、统计、增量监控、交付校验；Agent（语义检索 + LLM）负责相关性判断、跨源冲突处理、语义摘要、影响与建议。
- **终稿效果**：两份终稿分别包含 28/38 条可核验链接、24/37 个明确日期、24/52 处数字主张，且全部通过校验；相比之下无脚本基线只有 7/8 条链接、1/9 个明确日期、1/3 处数字主张。
- **不要犯的错**：把脚本输出直接当结论。本实验中“脚本金额抽取 0/34”若未经 Agent 复核就写进报告，会得出“近两年 ESG 招标没有披露金额”的错误结论。
- **工程改进方向**：① 搜索后端做成可插拔适配器（360/Bing/API Key），失败自动重试与退避；② 对摘要短缺的页面强制抓取正文；③ 在金额抽取规则外增加 LLM 兜底标注；④ 保留 `deduped`、`failed_queries` 字段用于实验复现。

## 五、交付物索引

- 两个 Skill：`.codebuddy/skills/esg-monthly-report/`、`.codebuddy/skills/esg-tender-intel/`（各含 SKILL.md、scripts/、references/、assets/）
- 案例报告：`案例一_中国神华ESG月报_20261025-20261125.md`、`案例二_ESG招投标信息汇总报告_20241125-20261125.md`、`案例二_每日招标监控_20261125.md`
- 无脚本基线：`实验_无Script基线/案例一_无脚本基线.md`、`案例二_无脚本基线.md`
- 实验数据：`运行日志与中间数据/`（compare_*.json/csv/md、monitor_*.md、case1/case2_search.json、case1/case2_evidence.json、case2_curated.json、*_validation.json）
