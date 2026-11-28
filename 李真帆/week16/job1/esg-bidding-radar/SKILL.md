---
name: esg-bidding-radar
description: 汇总 ESG、可持续发展、双碳相关的招标与中标信息。回顾模式统计近 N 年的中标情况、热点主题与中标金额分布并成文；监控模式发现新增招标、生成日报并推送。当用户提到 ESG 招标、ESG 中标、可持续发展报告编制招标、碳核查 碳盘查 碳足迹 碳资产 项目中标金额、双碳 项目招标、招标监控日报时使用。示例："汇总近两年 ESG 相关中标情况并分析"、"看看最近一周有哪些 ESG 相关招标"。
argument-hint: "[回顾 近N年 | 监控 最近N天]（可省略）"
---

# ESG 招标雷达

两种模式，按用户的话意判断。说"汇总、统计、分析、近 N 年"是回顾模式；说"监控、每天、最新、最近几天、推送"是监控模式。两种都要时先回顾后监控。监控中发现的、落在回顾区间内的记录并入回顾的 `bids.csv`，并在 `trace.md` 标明来自监控阶段。

## 回顾模式

### 1. 定范围

- 时间窗：取参数里的年限，缺省近 2 年。
- 关键词：按 `references/scope-and-keywords.md` 的词族和排除规则执行。
- 通知类型：金额统计只收中标、成交、中选结果类公告。招标公告、竞争性磋商公告只列进"进行中的招标机会"。
- 输出目录：`output/esg-bidding-radar/review_<起>_<止>/`。

### 2. 列检索计划

读 `references/sources.md`，按其中"回顾检索式清单"从高到低执行。预算用完即止，没执行的检索式在 `search_plan.md` 里标"未执行"。

### 3. 检索与取证

每条记录整理成一行写入 `bids.csv`，表头固定：

```
record_id,notice_type,title,project,purchaser,winner,amount_wan,amount_basis,notice_date,province,project_type,url,evidence_level
```

- `notice_type` 取 award（中标结果，含候选人公示）或 tender（招标中）。
- `amount_wan` 只填公告里明确写出的数字，单位万元。没有就留空，不估算。
- `amount_basis` 写金额是什么：中标金额、候选人报价、预算或最高限价、空。tender 行只能填预算或最高限价。
- `evidence_level` 取 full（打开过原文）或 snippet（仅搜索摘要）。
- `project_type` 取值见 `references/scope-and-keywords.md` 第 3 节。

取证要点：

- 金额、中标人、招标人以公告原文为准。摘要里已有金额和中标人的，可以只依据摘要，但要标 `snippet`。
- 同一公告包含多个包或标段时拆成多行，共用同一个 URL，每行有各自的中标人和金额。
- 候选人公示阶段的结果归入 award，金额填候选人报价，`amount_basis` 写"候选人报价"。
- 公告写明"失败""废标""终止"的，不算中标记录，不收进 `bids.csv`。
- 标题带"碳"字的，先按排除规则判断是不是真的 ESG 项目，再决定收不收。
- 检索式里的时间写具体月份或年份，如"2026年11月"。不要写"本周""最近"，搜索会忽略。不要用 `site:`，会让搜索报错。
- 预算：检索不超过 30 次，网页读取不超过 15 次。读取优先级：一个公告含多个包的（读一次能得到多条记录）、金额大的、信息不全的记录。每次读取（包括失败重试）都计入预算。
- 公告聚合页、PDF 通常读不出内容，不要在它们上面花预算。需要细节时找招标人官网的结果公告或媒体文字稿。

### 4. 统计

基于 `bids.csv` 里的 award 记录计算。金额统计只用 `amount_basis` 为"中标金额"的记录，候选人报价和预算单独说明。样本少的时候只做描述，不下趋势结论。同一家采购人贡献多个包时，指出它对分布的影响。

- 总量：记录数、披露金额的条数、金额合计、均值、中位数。
- 时间分布：按季度的条数与金额。
- 金额分布：10 万以下、10–50 万、50–100 万、100–500 万、500 万以上。
- 项目类型分布：条数与金额合计。
- 地域分布：前 10 个省份。
- 采购人类型分布。
- 中标机构格局：出现次数最多的前 10 家，及各自擅长的项目类型。

写报告前，用一条命令重新核对 `bids.csv` 的行数和金额合计。

### 5. 成文

按 `references/report-template.md` 写 `report.md`，并生成 `sources.jsonl`，格式如下：

```json
{"id":"S1","title":"...","publisher":"...","published":"2026-11-02","url":"...","section":"bid","verified":true}
```

一条记录对应一行。`verified` 对应 `evidence_level` 是否为 full。同一公告拆成多行的，每行各给一个编号。

## 监控模式

### 1. 定范围

- 时间窗：取参数里的天数。缺省读取 `output/esg-bidding-radar/state/seen.json` 里的 `last_run`，取其后的日期；没有该文件时取最近 7 天。
- 关键词与排除规则同回顾模式。

### 2. 检索新增

按 `references/sources.md` 的"监控检索式清单"执行，把 `{月}` 换成具体月份。预算：检索不超过 12 次，网页读取不超过 6 次。

### 3. 去重

与 `seen.json` 里已推送的 URL 比对，已推送的不再出现。公告日期在时间窗起点附近、仍在报名期内的招标，可以收录，并在项目名后注明公告日期。

### 4. 生成日报

按 `references/daily-brief-template.md` 写 `output/esg-bidding-radar/daily/<日期>.md`。

### 5. 推送

用户给了 webhook（企业微信、钉钉、飞书机器人地址）时，把日报正文用一条 curl 命令 POST 过去。没给就只落盘，并在汇报里说明。

### 6. 更新状态

把本次出现的全部 URL 写回 `seen.json`，保留原有的：`{"last_run":"YYYY-MM-DD","urls":[...]}`。

## 交付前质检

- 每条记录的 URL 都来自本次真实的检索结果。
- 金额只来自公告或摘要原文，没有估算。`amount_wan` 与 `amount_basis` 对得上。
- 回顾报告写明样本量，并说明样本不是全量。
- 监控日报里没有重复推送的条目。
- 统计数字与 `bids.csv` 重新核对过。

## 产物

```
回顾：output/esg-bidding-radar/review_<起>_<止>/
      report.md、bids.csv、sources.jsonl、search_plan.md、trace.md
监控：output/esg-bidding-radar/daily/<日期>.md
      output/esg-bidding-radar/state/seen.json
```

`trace.md` 记录：检索次数、命中与去重数量、剔除清单（标题、URL、理由）、未能打开的来源、来自监控阶段的记录。

## 约束

只用内置搜索与网页读取工具，不编写抓取脚本。采购类站点读取失败是常态，失败就换来源。
