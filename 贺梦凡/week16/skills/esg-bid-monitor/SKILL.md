---
name: esg-bid-monitor
description: "检索近两年ESG、可持续发展、双碳中标并分析热点与金额分布；按日监控新招标，去重后推送。用户要求中标汇总、招标监控或每日推送时使用。"
metadata: {"openclaw":{"emoji":"📣"}}
---

# ESG投标信息汇总

## 任务要求

1. 汇总过去2年ESG、可持续发展、双碳相关的中标情况，分析汇总热点招标情况及中标金额分布。
2. 监控新的跟ESG相关的招标情况每天推送新的招标信息。

先判断模式：

- 用户要汇总、复盘、金额分布、热点招标：走「两年汇总」。
- 用户要监控、每天推送、今日招标：走「每日监控」。
- 用户要把案例二整体做完：先交付两年汇总，再登记每日监控，并给出今天这一份推送。

未指定日期时，两年汇总的窗口是今天往前 24 个月（含今天）。每日监控看过去 48 小时，用来接住晚发布的公告。

## 先读再做

1. 读 [search-plan.md](search-plan.md)，按口径决定一条公告进不进样本。
2. 两年汇总在写正文前读 [report-template.md](report-template.md)。

## 证据规则

先用脚本检索并抽出记录，再交给已有的统计脚本。抽取脚本只把页面原句里标明「中标金额」或「成交金额」的数字写入 `amount_cny`。预算和限价留空。

```bash
python "{baseDir}/scripts/collect_notices.py" --since YYYY-MM-DD --until YYYY-MM-DD --out reports/esg-bids/records.json
python "{baseDir}/scripts/analyze_bids.py" "reports/esg-bids/records.json" --since YYYY-MM-DD --until YYYY-MM-DD
```

`{baseDir}` 只在 OpenClaw 中展开。模型不手抄金额。记录太少时，用重复的 `--query` 再跑 `collect_notices.py`，然后重新统计。

脚本整段失败时，才改用环境自带的网页搜索和网页打开。公告标题、采购人、金额、日期、中标人，必须打开公告原文后写入。搜索摘要里的金额不能直接入库。

- 金额字段只填中标金额或成交金额，单位折算成人民币元。预算、限价、控制价不能当成中标金额。
- 原文没有金额时，`amount_cny` 留空，禁止估算。
- `include_reason` 必须是原文里的短句，并且含有检索计划中的纳入关键词。
- 搜不到就交付小样本，并写明覆盖不到哪里。禁止编造公告来把分布图填满。
- 同一公告的转载只留一条，优先留政府采购网、公共资源交易平台或采购人官网。

## 两年汇总

```
进度：
- [ ] 写明起止日期和纳入、排除口径
- [ ] 跑完最低查询集，打开每条入选公告的原文
- [ ] 把入选记录写成 UTF-8 JSON 数组
- [ ] 运行 analyze_bids.py，退出码 2 也保留它的标准输出
- [ ] 围绕脚本输出写判断，不另行心算金额
- [ ] 运行 check_report.py，直到 OK
```

记录至少包含：`title`、`url`、`publish_date`（YYYY-MM-DD）、`buyer`、`winner`、`region`、`topic`、`doc_type`、`amount_cny`、`amount_raw`、`include_reason`、`source_name`。`doc_type` 只用：招标公告、采购意向、候选人公示、中标公告、成交公告。

```bash
python "{baseDir}/scripts/analyze_bids.py" "records.json" --since YYYY-MM-DD --until YYYY-MM-DD
```

`{baseDir}` 只在 OpenClaw 里展开。别处把 `{baseDir}` 换成这个技能目录。`python` 不可用时改用 `python3`。

脚本负责去重、分档、披露率、中位数和主题计数。正文里的金额、占比、中位数从「脚本统计」原文抄录。觉得数字不对，就改 JSON 再跑，不要在散文里改数。

报告存到 `reports/esg-bids/YYYYMMDD-2y.md`。检查：

```bash
python "{baseDir}/scripts/check_report.py" "reports/esg-bids/YYYYMMDD-2y.md"
```

退出码不是 0 就改到通过，然后再交给用户。对话里同时给出路径和执行摘要。

## 每日监控

只推送招标公告和采购意向，不把中标结果当成新招标。步骤固定：

1. 按 search-plan 的每日查询检索，打开新公告原文，写成 JSON 数组。
2. 先做一次不写台账的去重：

```bash
python "{baseDir}/scripts/ledger.py" --ledger "data/esg-bid-ledger.json" --incoming "incoming.json"
```

3. 用标准输出里的新增记录写推送稿。没有新增时，全文只有标题、检索窗口和这一句：`今日无新增ESG相关招标。`
4. 推送稿确认要发出之后，再执行同一命令并加上 `--apply`。稿子没发出，就不要 `--apply`。
5. 检查：

```bash
python "{baseDir}/scripts/check_report.py" --mode daily "reports/esg-bids/daily/YYYY-MM-DD.md"
```

推送稿存到 `reports/esg-bids/daily/YYYY-MM-DD.md`。每条分开写，包含采购人、发布日期、地区、预算或限价、截止时间、主题、相关原因、链接。相关原因引用原文短句。

用户要求每天推送，且当前环境有 `openclaw` 命令时，先运行 `openclaw automations list`。还没有名为「ESG招标日报」的任务才登记：

```bash
openclaw automations create "30 8 * * 1-5" "请按 esg-bid-monitor 技能的每日监控模式执行。检索过去48小时ESG、可持续发展、双碳相关招标公告和采购意向，打开原文核对后写入 JSON，用该技能的 ledger.py 对照 data/esg-bid-ledger.json 去重。只推送新增。没有新增时只输出：今日无新增ESG相关招标。不要编造公告。推送稿写入 reports/esg-bids/daily/当天日期.md，检查通过后再 --apply 台账。" --name "ESG招标日报" --tz "Asia/Shanghai" --session isolated --exact
```

没有 `openclaw` 命令时，照常交付今天的推送，并把上面的命令原文给用户，说明自动档还没登记。
