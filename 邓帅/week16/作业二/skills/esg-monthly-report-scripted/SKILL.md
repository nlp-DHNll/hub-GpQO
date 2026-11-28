---
name: esg-monthly-report-scripted
description: 当使用者要给一家企业（客户）编写 ESG 月报，并希望检索、抓取、筛选交给确定性脚本时使用，例如「用脚本版出一份中国神华的 ESG 月报」「跑脚本流水线做 ESG 月报」「skill 带脚本再做一次月报」。不适用于招投标情报（用 esg-bid-radar-scripted），也不适用于明确要求零脚本的运行（用 esg-monthly-report）。
metadata:
  version: "0.1.0"
---

# ESG 月报（脚本版）

## 概览

脚本做确定性的事：检索、抓取、筛选、统计、渲染、核验。你做需要判断的事：**复核脚本拿不准的证据，撰写影响与建议、下月关注清单。**

核心原则不变：每条进结论的事实背后都有一条打开原文核对过的证据；数字、角标、表格由脚本从 `data.json` 生成，你不另算一套。

## 何时触发

使用者点名了本 skill，或者说「用脚本 / 流水线 / 高代码」出 ESG 月报。只给一句话「做一份 ESG 月报」时，零脚本版（esg-monthly-report）也能做；两版并存时按使用者的说法选。

## 流程

五步，按顺序做。命令都在 week16 目录下执行；`<运行目录>`、客户、行业、时间窗以无头运行的提示词为准（没给时默认 `邓帅/week16/runs/<YYYYMMDD-HHMMSS>_monthly-report_scripted/`、中国神华、煤炭·能源、成文日前 30 天）。

### 1. 收集：检索 → 抓取 → 筛选

```bash
/opt/miniconda3/envs/py312/bin/python 作业二/scripts/run.py collect --case monthly-report \
  --client 中国神华 --industry 煤炭·能源 --start 2026-10-28 --end 2026-11-26 --budget 20 --out <运行目录>
```

要跑 3–8 分钟，调用时把超时设到 600000 毫秒。中途被打断就原样再跑一遍——它按地址缓存，会接着做。
跑完读它打印的摘要：`searches`（各路成功与失败）、`pages_fetched`、`records`（登记的证据数）、`needs_review`（待你复核的条数）、`model_usage`。
产物：`data.json`（证据表）、`review.json`（待复核清单）、`work/`（中间结果）。

### 2. 复核证据

读 `<运行目录>/review.json`。每条有 `issues`（脚本为什么拿不准）和 `record`（当前登记）。按原因处理：

| issue | 怎么处理 |
|---|---|
| 摘录在所取的正文里找不到，已降为仅见摘要 | 用读页工具打开 `url`，从原文里逐字找一句不超过 50 个字符的话；找得到就把 `record.quote` 换成它、`verification` 改成 `verified`；找不到就保持仅见摘要 |
| 范围判断与关键词规则相反 | 看标题与采购内容，以你的判断为准，必要时改 `in_scope` |
| 摘录超过 50 字，已截到 50 字 | 看截断后的半句话是否还成立，不成句就从原文另取一句 |

直接用编辑工具改 `data.json` 里对应的记录（按 `url` 找）。只改有问题的条目，不要动别的字段和 `id`。

### 3. 起草分析

```bash
/opt/miniconda3/envs/py312/bin/python 作业二/scripts/run.py summarize --out <运行目录>
```

模型依据「已核实」的证据写一份初稿到 `analysis.json`：`summary`、`policy`、`industry`、`company_facts`、`advice`、`benchmark_intro`、`benchmark`、`watchlist`、`method_notes`。

### 4. 改写结论与建议（你的活）

读 `analysis.json`，把它当成初稿，用你的判断改写后写回同一个文件（必须是合法 JSON，字段名不变）：

- 必须重写：`advice`（影响与建议：针对客户的具体情况，一张 Markdown 表格「序号 | 建议 | 依据」）、`watchlist`（下月关注清单，同样是一张表格）、`company_facts`（客户在时间窗内的动态；没有就如实写）。
- 通读其余各段：去掉空话与重复，把和客户关系不大的内容删掉或压缩；初稿只看过证据表，没看过原文，你若发现某条结论站不住，就改掉它。
- 每条事实句末的角标 `[n]` 只能是 `data.json` 里已有的角标编号；只有核实状态为 `verified` 的证据能进结论。不要引入证据表以外的事实，不要新造角标。
- 金额、数量照抄证据表里的数字。

### 5. 生成报告并核验

```bash
/opt/miniconda3/envs/py312/bin/python 作业二/scripts/run.py build --out <运行目录>
```

它依次做统计、渲染、核验，写出 `report.md` 与 `run.json`（已存在则不覆盖），并打印：`passed`（验收器是否通过）、`failed_rules`、`problems`（角标对不上之类的硬问题）、`warnings`。
有 `problems` 或 `passed` 为 false：按提示改 `analysis.json` 或 `data.json`，再跑一遍 `build`。`passed` 为 true 才算完成。

## 三件产物

| 文件 | 谁写 | 内容 |
|---|---|---|
| `report.md` | 脚本（`build`） | 报告正文：开头声明、七个规定章节、待核实事项、证据表附录 |
| `data.json` | 脚本（`collect`）+ 你的复核 | 证据表，每条八个契约字段 |
| `run.json` | 运行器或脚本（`build`） | 运行记录；不要自己写 |

## 常见错误

| 错误 | 后果 | 改法 |
|---|---|---|
| 跳过第 4 步，直接拿初稿交差 | 结论是照证据表复述，没有针对客户的判断 | 第 4 步是脚本版里唯一必须由你完成的分析工作 |
| 改写时写了证据表里没有的角标 | `build` 报「正文角标在证据表里没有对应记录」 | 只用已有的角标编号 |
| 自己改 `report.md` | 下次 `build` 会覆盖 | 改 `analysis.json` 与 `data.json`，报告由脚本生成 |
| `collect` 超时后换参数重跑 | 同一目录里混进两套检索结果 | 原样重跑；确实要换参数就换一个运行目录 |
