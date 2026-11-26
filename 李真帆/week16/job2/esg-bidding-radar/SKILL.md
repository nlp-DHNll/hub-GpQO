---
name: esg-bidding-radar
description: 汇总 ESG、可持续发展、双碳相关的招标与中标信息。回顾模式统计近 N 年的中标情况、热点主题与中标金额分布并成文；监控模式发现新增招标、生成日报并推送。脚本负责搜索结果归一、关键词筛选、抓取、结构化提取、统计画图、合成与复核，agent 负责列检索计划、抽查更正、写分析。当用户提到 ESG 招标、ESG 中标、可持续发展报告编制招标、碳核查 碳盘查 碳足迹 碳资产 项目中标金额、双碳 项目招标、招标监控日报时使用。示例："汇总近两年 ESG 相关中标情况并分析"、"看看最近一周有哪些 ESG 相关招标"。
argument-hint: "[回顾 近N年 | 监控 最近N天]（可省略）"
---

# ESG 招标雷达（脚本版）

两种模式，按用户的话意判断。说"汇总、统计、分析、近 N 年"是回顾模式；说"监控、每天、最新、最近几天、推送"是监控模式。两种都要时先回顾后监控。

重复且确定的动作交给 `<skill目录>/scripts/` 里的脚本：关键词筛选、抓取、结构化提取、统计画图、合成报告、复核。agent 做三件事：列检索计划，抽查更正，写分析和建议。

## 环境

- Python 3.10 以上，依赖见作业目录的 `requirements.txt`。
- 配置读 `.env`，脚本从当前目录向上查找。`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`CHAT_MODEL` 用于结构化提取；`BOCHA_API_KEY`、`TAVILY_API_KEY`、`SERPER_API_KEY` 任选其一用于搜索，可以缺省。
- 命令都在作业目录下运行，用虚拟环境里的解释器。命令里的 `<skill目录>` 指本 SKILL.md 所在的目录，其余尖括号占位符按"定范围"一节的取值替换。中间文件写进输出目录，抓取缓存在 `cache/`。

关键词和排除规则在 `<skill目录>/references/keywords.yaml`，给脚本读；项目类型、采购人类型的含义在 `<skill目录>/references/scope-and-keywords.md`，给人读。

## 回顾模式

### 1. 定范围

- 时间窗：取参数里的年限，缺省近 2 年。
- 通知类型：金额统计只收中标、成交、中选结果类公告。招标公告、竞争性磋商公告只列进"进行中的招标机会"。
- 输出目录：`output/esg-bidding-radar/review_<起>_<止>/`。

下文用 `<输出目录>` 指代它，`<起>`、`<止>` 指代时间窗两端，`<天数>` 指代时间窗的天数。

### 2. 列检索计划

读 `<skill目录>/references/sources.md` 的"回顾检索式清单"，按时间窗调整年份后写进 `queries.txt`，一行一个。

### 3. 联网搜索

配了搜索 API key 时：

```
python <skill目录>/scripts/search.py --plan queries.txt --out <输出目录>/results.jsonl --days <天数>
```

没配 key 时，agent 用内置搜索逐条执行 `queries.txt`，把每条结果写进一个 TSV 文件：带表头，Tab 分隔，列依次是 `query`、`title`、`url`、`published`、`snippet`，一条结果一行。`published` 照搜索结果原样写；字段里不要出现制表符和换行。全部搜完后：

```
python <skill目录>/scripts/search.py --provider file --raw <TSV 文件> --out <输出目录>/results.jsonl
```

### 4. 关键词筛选

```
python <skill目录>/scripts/filter.py --mode bid --in <输出目录>/results.jsonl --out <输出目录>/bid_candidates.jsonl --rules <skill目录>/references/keywords.yaml
```

读输出目录里同名的 `.rejected.jsonl` 抽查剔除项。被"未命中关键词"剔除但确实是 ESG 项目的，把词补进 `<skill目录>/references/keywords.yaml` 再跑。`tier` 为 extended 的条目由 agent 看标题逐条判断，明显不是 ESG 项目的删掉。

### 5. 抓取原文

```
python <skill目录>/scripts/fetch.py --in <输出目录>/bid_candidates.jsonl --out <输出目录>/bid_pages.jsonl --limit 200
```

### 6. 结构化提取

```
python <skill目录>/scripts/summarize.py --schema bid --in <输出目录>/bid_pages.jsonl --out <输出目录>/bids.jsonl
```

抽查 `bids.jsonl`，发现下列情况直接改卡片字段，并记进 `trace.md`：

- `is_esg` 为 false，但标题明显是 ESG 项目。
- `amount_wan` 和 `amount_text` 对不上，或把预算填成了中标金额。
- `notice_type`、`project_type`、`purchaser_type` 明显不对。
- 同一公告包含多个包或标段：复制该行，逐行改 `project`、`winner`、`amount_wan`、`amount_text`。
- 公告写明"失败""废标""终止"的：把 `is_esg` 改成 false。

### 7. 统计与画图

```
python <skill目录>/scripts/stats.py --in <输出目录>/bids.jsonl --out <输出目录>/stats.json --charts-dir <输出目录>/charts
```

### 8. 写作

- 正文里的条数、金额、分布只从 `stats.json` 取，不自己数。图表用相对路径引用，如 `![按季度的中标条数](charts/quarterly.png)`。
- 按 `<skill目录>/references/report-template.md` 写 `body.md`。写到的具体项目标 `[S#]`，表格的来源列也一样。
- 样本不是全量，要写明样本量。同一家采购人贡献多个包时，指出它对分布的影响。样本少于 3 条的类型写"样本不足"，不下结论。
- 不要写来源附录，附录由脚本生成。

### 9. 导出来源，合成报告，复核

```
python <skill目录>/scripts/sources.py --schema bid --in <输出目录>/bids.jsonl --out <输出目录>/sources.jsonl
python <skill目录>/scripts/render.py --body <输出目录>/body.md --sources <输出目录>/sources.jsonl --stats <输出目录>/stats.json --out <输出目录>/report.md --html <输出目录>/report.html --title "ESG 相关招投标回顾报告" --generated-by esg-bidding-radar
python <skill目录>/scripts/check_report.py --report <输出目录>/report.md --sources <输出目录>/sources.jsonl --stats <输出目录>/stats.json --out <输出目录>/check.json --since <起> --until <止> --require "总体情况,热点主题,金额分布,中标机构"
```

处理复核结果，改完重新合成、重新复核：

- "统计数字……正文里找不到的"必须为空。
- 悬空引用必须清零。
- "标题对不上"的来源逐条看，对不上就改正文。

## 监控模式

### 1. 定范围

- 时间窗：取参数里的天数，缺省 7 天。
- 状态文件 `output/esg-bidding-radar/state/seen.json` 记录上次运行日期和已推送的链接，由脚本维护，不要手工改。

### 2. 取搜索结果

没配搜索 API key 时，agent 用内置搜索按 `<skill目录>/references/sources.md` 的"监控检索式清单"搜（不超过 12 次），写成 TSV，再 `python <skill目录>/scripts/search.py --provider file --raw <TSV 文件> --out monitor_results.jsonl`。配了 key 时这一步省略。

### 3. 生成日报

```
python <skill目录>/scripts/monitor.py --state output/esg-bidding-radar/state/seen.json --days <天数> --out-dir output/esg-bidding-radar/daily --rules <skill目录>/references/keywords.yaml [--results monitor_results.jsonl] --fetch --llm [--webhook <机器人地址>]
```

- 脚本自己做这几件事：关键词筛选、与已推送记录比对、抓取新增条目的原文、提取截止时间和金额、写日报、更新状态文件。给了 `--webhook` 就推送。
- 去掉 `--fetch --llm` 就是纯关键词规则的线索清单，不调用大模型，可以挂到计划任务上无人值守。这种方式需要搜索 API key，由脚本自己搜索。

### 4. 复核

```
python <skill目录>/scripts/check_report.py --report output/esg-bidding-radar/daily/<日期>.md --sources output/esg-bidding-radar/daily/<日期>.sources.jsonl --out output/esg-bidding-radar/daily/<日期>.check.json --since <起> --until <止> --require "新增,提示"
```

### 5. 人工补充

日报里信息不全但重要的线索（缺截止时间、资格要点），用内置搜索摘要补上，补了来源就同步进当日的 `sources.jsonl`，然后重新复核。

公告日期在时间窗起点附近、仍在报名期内的招标没有被收进来时，把 `--days` 调大重跑。状态文件只记已推送的链接，不会重复推送。

## 交付前质检

- 金额只来自公告或摘要原文，没有估算。
- 回顾报告写明样本量，并说明样本不是全量。
- 监控日报里没有重复推送的条目。
- 复核结果里没有悬空引用，统计数字都在正文里找得到。

## 产物

```
回顾：output/esg-bidding-radar/review_<起>_<止>/
      report.md、report.html、body.md、bids.jsonl、stats.json、charts/、sources.jsonl、check.json、search_plan.md、trace.md
监控：output/esg-bidding-radar/daily/<日期>.md、<日期>.sources.jsonl、<日期>.check.json
      output/esg-bidding-radar/state/seen.json
```

## 脚本

| 脚本 | 做什么 |
|---|---|
| `search.py` | 调搜索源，或读入 agent 导出的结果，输出统一格式并去重 |
| `filter.py` | 按关键词和排除规则筛出 ESG 相关线索 |
| `fetch.py` | 抓原文，抽页面标题、发布日期、正文 |
| `summarize.py` | 调大模型提取采购人、中标人、金额、类型等结构化字段 |
| `stats.py` | 聚合统计并画图 |
| `sources.py` | 从提取结果导出来源清单 |
| `render.py` | 合成正文与附录，转成 HTML |
| `check_report.py` | 复核引用、来源可核验性、统计数字 |
| `monitor.py` | 增量监控：去重、日报、推送、更新状态 |

## 约束

- 来源只从 `bids.jsonl` 和 monitor 的输出里来。不凭记忆补充事实。
- 脚本报错时读错误信息、修参数，不要绕开脚本手工抓取。
