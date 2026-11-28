---
name: esg-monthly-report
description: 生成企业 ESG 月报。联网检索指定时间窗内的 ESG 政策、评级、标准动态，客户所在行业的新闻与最佳实践，客户公司动态的 ESG 影响及对标企业关键行动，逐条核实来源与日期后形成带引用的月报。脚本负责扫描栏目页、抓取、筛选、提炼、合成与复核，agent 负责列检索计划、判断取舍、写分析。当用户提到 ESG 月报、可持续发展月报、ESG 月度动态、ESG 政策追踪、对标企业 ESG 行动、给某公司做 ESG 简报时使用。示例："给中国神华做一份 11 月的 ESG 月报"、"梳理过去一个月煤炭行业的 ESG 动态"。
argument-hint: "[客户名称] [时间窗，如 2026-11 或 最近30天]"
---

# ESG 月报（脚本版）

为一家具名企业产出可直接交给客户的 ESG 月报。重复且确定的动作交给 `<skill目录>/scripts/` 里的脚本：扫描栏目页、抓取、筛选、提炼证据卡、合成报告、复核。agent 做三件事：列检索计划，判断取舍，写分析和建议。

## 环境

- Python 3.10 以上，依赖见作业目录的 `requirements.txt`。
- 配置读 `.env`，脚本从当前目录向上查找。`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`CHAT_MODEL` 用于提炼；`BOCHA_API_KEY`、`TAVILY_API_KEY`、`SERPER_API_KEY` 任选其一用于搜索，可以缺省。
- 命令都在作业目录下运行，用虚拟环境里的解释器。命令里的 `<skill目录>` 指本 SKILL.md 所在的目录，其余尖括号占位符按"确定输入"一节的取值替换。中间文件写进输出目录，抓取缓存在 `cache/`。

## 确定输入

- 客户：从参数取，缺省为中国神华。
- 时间窗：从参数取。`YYYY-MM` 表示该自然月，`最近N天` 表示截至当天的 N 天；缺省为截至当天的最近 30 天。
- 输出目录：`output/esg-monthly-report/<客户>_<起>_<止>/`，开工前先建好。
- 客户画像：客户是中国神华时读 `<skill目录>/references/client-china-shenhua.md`；其他客户按 `<skill目录>/references/search-playbook.md` 第 1 节先建画像。

下文用 `<输出目录>` 指代它，`<起>`、`<止>` 指代时间窗两端，`<天数>` 指代时间窗的天数。

## 工作流

### 1. 列检索计划

读 `<skill目录>/references/search-playbook.md`，把需要联网搜的检索式写进 `queries.txt`，一行一个，同时记进 `search_plan.md`。栏目页由脚本扫描，不用写成检索式。政策 6 条、评级标准 5 条、行业 5 条、公司 4 条、对标 3 条左右，总数 23 条上下，给补搜留出余量。

### 2. 扫描权威栏目页

```
python <skill目录>/scripts/scan.py --lists <skill目录>/references/source_lists.yaml --out <输出目录>/list_items.jsonl --since <起> --until <止> --rules <skill目录>/references/keywords.yaml
```

### 3. 联网搜索

配了搜索 API key 时：

```
python <skill目录>/scripts/search.py --plan queries.txt --out <输出目录>/results.jsonl --days <天数>
```

没配 key 时，agent 用内置搜索逐条执行 `queries.txt`，把每条结果写进一个 TSV 文件：带表头，Tab 分隔，列依次是 `query`、`title`、`url`、`published`、`snippet`，一条结果一行。`published` 照搜索结果原样写（"2026-11-15 00:00:00"、"6天前"、空都行）；字段里不要出现制表符和换行；日期为空或明显在时间窗外的结果也照写，后面由脚本统一处理。全部搜完后：

```
python <skill目录>/scripts/search.py --provider file --raw <TSV 文件> --out <输出目录>/results.jsonl
```

### 4. 抓取与筛选

```
python <skill目录>/scripts/fetch.py --in <输出目录>/results.jsonl <输出目录>/list_items.jsonl --out <输出目录>/pages.jsonl --since <起> --until <止> --limit 200
python <skill目录>/scripts/filter.py --mode news --in <输出目录>/pages.jsonl --out <输出目录>/candidates.jsonl --since <起> --until <止> --rules <skill目录>/references/keywords.yaml
```

读 filter 打印的剔除统计。被"关键词不足"剔除但明显相关的条目，调低 `--min-score` 重跑。

### 5. 提炼证据卡

```
python <skill目录>/scripts/summarize.py --schema evidence --in <输出目录>/candidates.jsonl --out <输出目录>/cards.jsonl --context "客户=中国神华；行业=煤炭；对标=中煤能源、兖矿能源、陕西煤业、山西焦煤、淮北矿业；控股股东=国家能源集团；时间窗=<起> 至 <止>"
```

需要细节时读 `cards.jsonl`，每张卡有章节、相关性、影响等级和要点。不要回头整页读网页。

### 6. 判断与写作

- 复核模型给出的章节和影响等级，明显不对的在正文里改正，改动记进 `trace.md`。
- `section` 为 irrelevant、`relevance` 为 low 或 irrelevant 的卡片不进正文。
- 某章卡片不够时（政策 5 条以上、评级标准 2 条以上、行业 5 条以上、公司 2 条以上、对标 3 条以上），回到第 3 步补几条检索式，重跑第 3 到 5 步。脚本有缓存，不会重复抓取。仍不够就在报告里如实写"本期未检索到"。目标只是参考，不要用相关性低的卡片凑数，不得编造。
- 按 `<skill目录>/references/report-template.md` 写 `body.md`。写作规则：结论先行；每个事实后面标 `[S#]`，表格的来源列也一样；事实与判断分开，判断以"判断："开头；数字照抄卡片；建议写成可执行的动作。正文 2500–6000 字（表格文字计入）。不要写来源附录，附录由脚本生成。
- 对拿不准的卡片可以打开原文核对，不超过 8 次。核对后以原文为准，并记进 `trace.md`。
- 来源只从 `cards.jsonl` 来，不凭记忆补充事实。

### 7. 导出来源，合成报告

```
python <skill目录>/scripts/sources.py --schema evidence --in <输出目录>/cards.jsonl --out <输出目录>/sources.jsonl
python <skill目录>/scripts/render.py --body <输出目录>/body.md --sources <输出目录>/sources.jsonl --out <输出目录>/report.md --html <输出目录>/report.html --title "<客户> ESG 月度动态报告" --generated-by esg-monthly-report
```

`sources.jsonl` 是相关性达标的全部卡片，编号就是正文里的 `[S#]`。正文用不到的条目，从 `sources.jsonl` 里删掉再合成；删除后不要重新编号，保留空缺编号，正文里的 `[S#]` 不用改。正文要用的卡片不在里面的，不要手写来源。

### 8. 复核

```
python <skill目录>/scripts/check_report.py --report <输出目录>/report.md --sources <输出目录>/sources.jsonl --out <输出目录>/check.json --since <起> --until <止> --require "本期要点,政策,评级,行业,公司,对标,行动建议"
```

处理复核结果，改完重新合成、重新复核：

- 悬空引用和未被引用的来源必须清零。
- "标题对不上""标题部分对得上"的来源逐条看，对不上就从正文和 `sources.jsonl` 里去掉。
- "页面无法解析""打不开"的，在正文的局限说明里如实标注。

### 9. 过程记录

把各脚本的统计行、大模型 token 用量、人工改动（改了哪张卡的哪个字段、为什么）写进 `trace.md`。

## 产物

```
<输出目录>/
├── report.md        月报（交付物）
├── report.html      带样式的网页版
├── body.md          agent 写的正文
├── sources.jsonl    来源清单
├── cards.jsonl      证据卡
├── check.json       复核结果
├── search_plan.md   检索计划
├── queries.txt      检索式
└── trace.md         过程记录
```

## 脚本

| 脚本 | 做什么 |
|---|---|
| `scan.py` | 扫描权威栏目页，抽出时间窗内的条目 |
| `search.py` | 调搜索源，或读入 agent 导出的结果，输出统一格式并去重 |
| `fetch.py` | 抓原文，抽页面标题、发布日期、正文 |
| `filter.py` | 时间窗、去重、关键词相关性、剔除列表页和常规审批公示 |
| `summarize.py` | 逐篇调大模型，输出固定结构的证据卡 |
| `sources.py` | 从证据卡导出来源清单 |
| `render.py` | 合成正文与附录，转成 HTML |
| `check_report.py` | 复核引用、来源可核验性、时间窗、章节 |

## 约束

- 来源只从 `cards.jsonl` 来。不读整页网页写报告，不凭记忆补充事实。
- 脚本报错时读错误信息、修参数，不要绕开脚本手工抓取。
