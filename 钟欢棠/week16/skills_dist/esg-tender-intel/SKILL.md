---
name: esg-tender-intel
description: Aggregate and analyze ESG, sustainability and dual-carbon tender/award information over a lookback window (default 2 years), analyze hotspots and award-amount distribution, and generate a daily monitor that pushes newly discovered ESG tenders. Use for ESG 招投标汇总, 双碳中标情况分析, 中标金额分布, ESG 招标每日监控推送.
---

# ESG 招投标信息汇总与每日监控

## 触发与输入

在用户要求汇总 ESG/可持续发展/双碳相关中标情况、分析热点招标与中标金额分布、或每日推送新增 ESG 招标信息时使用。默认输入：

- 回溯窗口：最近 2 年（24 个月）
- 关键词：ESG、可持续发展、双碳、碳达峰/碳中和、碳管理、节能降碳、绿色建筑、能源托管、碳核算、绿色认证
- 输出路径：当前工作区 `作业成果/`
- 监控模式：以 `--state` 持久化去重状态，生成当日增量推送

## 核心流程

### 1. 检索词矩阵

按主题 × 公告类型组织检索式：主题词（见上）× 公告类型（中标公告、成交公告、结果公告、招标信息、采购需求）× 时间词（年份、月份）。重点来源：中国政府采购网、地方公共资源交易平台、中招国际招标、中国通用招标网、行业媒体。分类与字段规范见 `references/tender-taxonomy.md`。

### 2. 联网检索

- 使用语义检索工具（如 `web_search`）按主题分批检索，召回近 2 年真实公告；
- 同时运行确定性脚本补充覆盖并记录检索日志：

```bash
python <skill>/scripts/search_web.py --queries "ESG 中标公告 2026" "双碳 中标 金额 2025" \
  "可持续发展 成交公告 2026" "碳管理平台 中标 2026" \
  --out 作业成果/运行日志与中间数据/case2_search.json --max 10 --sleep 0.6 \
  --keywords ESG 可持续发展 双碳 中标 成交 金额 --reference-date 2026-11-25
```

### 3. 确定性结构化与统计

对检索池运行抽取式摘要，再运行招投标聚合脚本，得到统一的 CSV/JSON/统计表：

```bash
python <skill>/scripts/summarize.py --input 作业成果/运行日志与中间数据/case2_search.json \
  --out 作业成果/运行日志与中间数据/case2_evidence.json --limit 60 --fetch-limit 15

python <skill>/scripts/aggregate_tenders.py --input 作业成果/运行日志与中间数据/case2_evidence.json \
  --out-json 作业成果/运行日志与中间数据/case2_stats.json \
  --out-csv 作业成果/运行日志与中间数据/case2_tenders.csv \
  --out-md 作业成果/运行日志与中间数据/case2_stats.md --reference-date 2026-11-25
```

脚本按规则抽取中标单位、金额（统一为万元）、日期、项目编号与主题，并去重。脚本输出只是**候选事实表**：Agent 必须逐条复核金额单位、公告类型与原文一致性，剔除“招标预算”冒充“中标金额”的记录，存疑条目标注“待核验”。

### 4. 分析报告

按 `assets/report_template.md` 撰写，至少包含：

1. 样本说明与方法：公开网络检索样本，非全市场数据库，口径与局限必须显式说明；
2. 近 2 年中标总体情况：记录数、披露金额记录数、金额合计与中位数；
3. 热点招标主题分析：主题分布、代表项目、需求方类型、政策驱动因素；
4. 中标金额分布：区间表、头部项目、金额集中度、按年/月趋势；
5. 中标单位格局：高频中标机构、能力类型（认证/咨询/软件开发/能源服务）；
6. 机会判断与行动建议；
7. 来源附录与字段说明。

所有数字必须能回溯到 CSV 或来源链接；金额统一以万元呈现并在表头注明；对未披露金额的项目单独计数，不得按 0 计入均值。

### 5. 每日监控推送

使用持久化 state 做增量比对，只推送新增项：

```bash
python <skill>/scripts/monitor_daily.py --input 当日检索JSON \
  --state 作业成果/运行日志与中间数据/monitor_state.json \
  --out 作业成果/案例二_每日招标监控_YYYYMMDD.md --date YYYY-MM-DD
```

推送内容：新增数量、项目名、公告日期、来源、摘要、原文链接；无新增时明确写“今日无新增”。每日监控与历史汇总分开归档，state 文件不得删除。

### 6. 验证

```bash
python <skill>/scripts/validate_report.py --report <汇总报告.md> --type tender \
  --window-start 2024-11-25 --window-end 2026-11-25 \
  --out 作业成果/运行日志与中间数据/case2_validation.json
```

验证失败按 `references/quality-checklist.md` 修复后重跑。

## 异常处理

- 金额缺失：保留记录、标注“未披露”，不参与金额统计。
- “预算金额/最高限价”与“中标金额”同时出现：只取中标/成交金额，若无法区分则丢弃该条金额。
- 同一项目多次公告（变更/二次/结果公示）：按项目编号或标准化项目名去重，保留最新结果。
- 单位混用（元/万元/亿元）：由脚本统一换算后人工抽查至少 5 条。
- 搜索引擎限流或验证码：降低频率、换备用引擎，并在日志中记录失败检索式。
- 网页无法访问：使用检索摘要并降级证据等级，禁止补全未披露字段。

## 完成条件

汇总报告含全部 7 个部分、统计表与来源链接齐全、金额口径一致；每日推送为增量且可复现；验证脚本通过。
