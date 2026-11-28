---
name: esg-bid-radar-scripted
description: 当使用者要了解 ESG、可持续发展、双碳相关招标的情况，并希望检索、抓取、金额解析、统计、图表交给确定性脚本时使用，例如「用脚本版汇总近两年 ESG 中标情况」「跑流水线出双碳招标分析」「用脚本监控新的 ESG 招标」。不适用于 ESG 月报（用 esg-monthly-report-scripted），也不适用于明确要求零脚本的运行（用 esg-bid-radar）。
metadata:
  version: "0.1.0"
---

# ESG 招投标情报（脚本版）

## 概览

脚本做确定性的事：检索（智谱搜索 + 中国政府采购网站内直连）、抓取、字段抽取与金额换算、统计、图表、渲染、核验。
你做需要判断的事：**复核范围拿不准的招标，写解读。**

两种模式：**汇总模式**汇总时间窗内的中标情况并出图；**监控模式**只找基线日之后新发布的招标公告，出日报并更新已见清单。

## 何时触发

使用者点名了本 skill，或者说「用脚本 / 流水线 / 高代码」做招投标情报。请求里有「汇总 / 分析 / 两年 / 金额分布」是汇总模式；「监控 / 每天 / 新增 / 日报」是监控模式。

## 流程（汇总模式）

命令都在 week16 目录下执行；`<运行目录>` 与时间窗以无头运行的提示词为准（没给时默认 `邓帅/week16/runs/<YYYYMMDD-HHMMSS>_bid-radar_scripted/`、成文日前 24 个月）。

### 1. 收集

```bash
/opt/miniconda3/envs/py312/bin/python 作业二/scripts/run.py collect --case bid-radar --mode summary \
  --start 2024-11-26 --end 2026-11-26 --budget 40 --out <运行目录>
```

要跑 5–12 分钟，调用时把超时设到 600000 毫秒；中途被打断就原样再跑一遍，它按地址缓存接着做。
读摘要：`searches`（智谱搜索与政采网直连各成功多少）、`records`（登记的招标记录数）、`needs_review`。

### 2. 复核范围与金额

读 `<运行目录>/review.json`，按 `issues` 处理：

| issue | 怎么处理 |
|---|---|
| 范围判断与关键词规则相反 | 标题里既有专业服务词、又有工程 / 设备词。看采购内容：买的是方案、核算、报告、平台服务、培训 → `in_scope: true`；买的是工程、货物、设备 → `false` |
| 模型对范围或类型拿不准 | 同上，以你的判断为准；判不准的从保守，算边界外 |
| 金额写法在所取的正文里找不到 | 用读页工具打开 `url`，找到「中标（成交）金额」；能确定就补 `amount_text` 并换算成元写 `amount`，否则保持 `null` |
| 判为范围内但主题不在六类里 | 从六类里选最贴近的一个写进 `topic`；确实不属于专业服务就把 `in_scope` 改成 `false` |
| 标题含「工程/设备」类词 | 确认一下是不是专业服务，是就保留 |

范围内记录的 `topic` 只能是：咨询规划、碳排放核算与核查、报告编制与鉴证、碳资产管理与交易、双碳平台与监测系统、培训认证。
直接用编辑工具改 `data.json` 里对应的记录（按 `url` 找），不要动其它字段。

### 3. 起草解读

```bash
/opt/miniconda3/envs/py312/bin/python 作业二/scripts/run.py summarize --out <运行目录>
```

模型依据统计结果把解读初稿写进 `analysis.json`：`opening`、`topic_notes`、`amount_notes`、`trend_notes`、`buyer_notes`、`typical_notes`。

### 4. 改写解读（你的活）

读 `analysis.json`，按你的判断改写后写回同一个文件（合法 JSON，字段名不变，都是纯文本、各 1–3 句）：

- 数字只能用统计结果里的（样本量、金额可得率、各主题条数、金额合计），不要估算、不要引入外面的信息。
- 措辞写明「样本」：样本不是全量普查，样本少的时候要说明结论不稳。
- 加上对商务有用的判断：哪些主题值得跟进、去哪里找客户、报价大致什么量级。

### 5. 出图、渲染与核验

```bash
/opt/miniconda3/envs/py312/bin/python 作业二/scripts/run.py build --out <运行目录>
```

写出 `report.md`（含 `charts/` 下的四张图）与 `run.json`（已存在则不覆盖），打印 `passed`、`failed_rules`、`problems`、`warnings`。`passed` 为 true 才算完成；不通过就按提示改 `data.json` 或 `analysis.json` 再跑一遍。

## 流程（监控模式）

与汇总模式相同的五步，命令不同：

```bash
# 1. 收集：基线日是 --start；--seen 是已见清单，开始检索前脚本会把它复制为 seen_before.json
/opt/miniconda3/envs/py312/bin/python 作业二/scripts/run.py collect --case bid-radar --mode monitor \
  --start 2026-11-25 --end 2026-11-26 --budget 12 --seen runs/seen/scripted.json --out <运行目录>

# 5. 生成日报、核验，并把本次新增追加进已见清单
/opt/miniconda3/envs/py312/bin/python 作业二/scripts/run.py build --out <运行目录> --seen runs/seen/scripted.json
```

复核时重点看：公告类型是不是招标公告（`tender`）、发布日期是否严格晚于基线日——这两条脚本已经用代码卡过，你只需处理 `review.json` 里范围拿不准的条目。
没有新增时脚本照常出一份日报（写明「无新增」）。不要自己改已见清单，`build --seen` 会更新它。

## 三件产物

| 文件 | 谁写 | 内容 |
|---|---|---|
| `report.md` | 脚本（`build`） | 汇总报告（五个分析项 + 边界外附录 + 图表）或日报 |
| `data.json` | 脚本（`collect`）+ 你的复核 | 招标记录，每条十三个契约字段（日报另加 `deadline`、`summary`） |
| `run.json` | 运行器或脚本（`build`） | 运行记录；不要自己写 |
| `seen_before.json` | 脚本（仅监控模式） | 运行前已见清单的快照 |

## 常见错误

| 错误 | 后果 | 改法 |
|---|---|---|
| 跳过第 2 步 | 工程类项目混进样本，金额分布被带偏 | 逐条处理 `review.json` |
| 解读里出现统计结果以外的数字 | 报告与 `data.json` 对不上 | 数字只从统计结果里取 |
| 自己改 `report.md` 或已见清单 | 下次 `build` 会覆盖；去重依据被破坏 | 只改 `data.json` 与 `analysis.json` |
| 监控模式忘了带 `--seen` | `collect` 直接报错；`build` 不更新已见清单 | 两条命令都带上同一个 `--seen` |
