---
name: esg-monthly-report
description: Generate a client-ready ESG monthly report covering the past month's ESG policy, rating and standard developments, industry news and best practices, and client-specific ESG impacts with peer benchmarking. Use when asked for ESG 月报, ESG 月度监测, 可持续发展动态简报, or sustainability briefings for a listed company (e.g. 中国神华). Autonomously searches the web, filters evidence and writes a sourced Chinese report.
---

# ESG 月报生成

## 触发与输入

在用户要求生成 ESG 月报、月度 ESG 动态简报、企业可持续发展月度监测时使用。执行前确认以下输入；用户未指定时采用默认值并在报告中声明：

- 客户名称：默认“中国神华”
- 时间窗：默认最近一个自然月（以当前日期为终点）
- 对标企业：能源煤炭行业默认 中煤能源、兖矿能源、陕西煤业、国家能源集团
- 输出路径：默认当前工作区 `作业成果/`
- 语言：中文

## 核心流程

严格按以下顺序执行，禁止跳步。

### 1. 拆解检索矩阵

围绕四类问题各设计 3–5 条检索式，写入检索日志：

1. 政策/监管/标准/评级：交易所披露指南、中证ESG评价方法、工信部/发改委/生态环境部政策、国际ESG规则变化；
2. 行业层面：煤炭、电力、能源行业 ESG 新闻、最佳实践、绿色低碳技术、安全与生态治理；
3. 客户公司：客户 ESG 奖项、评级变化、碳减排/新能源项目、治理与披露动态、负面事件；
4. 对标企业：对标公司同期 ESG 关键行动、评级变化、披露亮点。

检索式应包含时间词（年月）、主体和主题词。来源优先级与检索式模板见 `references/source-priority.md`。

### 2. 自主联网检索

- 优先使用环境提供的语义检索工具（如 `web_search`）保证相关性，每个子问题至少检索 1 次；
- 使用 `scripts/search_web.py` 再做一轮确定性检索，获得可复现的检索日志、去重结果和排序分数，**补充**语义检索的盲区，不替代之；
- 记录每条检索式、命中数、保留数；目标：时间窗内有效证据不少于 12 条，且覆盖上述四类问题。

```bash
python <skill>/scripts/search_web.py --queries "2026年11月 ESG 政策 标准 评级" "中国神华 ESG 2026年11月" \
  --out 作业成果/运行日志与中间数据/case1_search.json --max 8 --days 40 \
  --keywords ESG 政策 评级 标准 碳 中国神华 --reference-date 2026-11-25
```

### 3. 筛选与深读

按 `references/source-priority.md` 的权威等级与时间窗筛选：剔除无关、重复、时间窗外、标题党与低质聚合页；同一事实优先引用一手来源。对最重要的 5–8 条调用网页抓取工具（如 `web_fetch`）深读，提取：发生日期、主体、事实、数字、原文措辞、可核验链接。证据分级 A（官方/原文）/B（权威媒体）/C（转载/聚合），冲突信息并列呈现并注明分歧。

可选确定性摘要脚本（抽取式、无 LLM，适合快速建立证据表，不直接作为最终表述）：

```bash
python <skill>/scripts/summarize.py --input 作业成果/运行日志与中间数据/case1_search.json \
  --out 作业成果/运行日志与中间数据/case1_evidence.json \
  --out-md 作业成果/运行日志与中间数据/case1_evidence.md --limit 30 --fetch-limit 12
```

### 4. 撰写报告

按 `assets/report_template.md` 组织，至少包含：

1. 本月概览：3–5 条核心判断，每条带日期与来源编号；
2. ESG 政策、评级、标准动态：逐条给出“事件—内容—对客户的影响—来源”；
3. 行业新闻与最佳实践：区分技术类、管理类、披露类实践，提炼可借鉴动作；
4. 客户公司动态与 ESG 影响：按 E/S/G 维度归类，给出影响判断（正面/中性/风险）与具体建议；
5. 对标企业关键行动：用对照表呈现对标企业动作、客户差距、可复制做法；
6. 风险提示与下月关注清单；
7. 附录：检索式清单、来源表（编号+标题+日期+链接+等级）、方法说明与局限。

写作规则：每个事实性句子必须带 `[n]` 来源编号；数字必须来自证据，禁止推测；“影响与建议”必须明确标注为分析判断；不确定处写明“公开信息未见披露”。

### 5. 验证与交付

```bash
python <skill>/scripts/validate_report.py --report <报告.md> --type monthly \
  --window-start 2026-10-25 --window-end 2026-11-25 \
  --evidence 作业成果/运行日志与中间数据/case1_evidence.json \
  --out 作业成果/运行日志与中间数据/case1_validation.json
```

验证不通过时按 `references/quality-checklist.md` 修复后重跑，最多 2 轮；仍不通过须在报告末尾披露未达标项。

## 异常处理

- 检索工具失败：记录失败检索式，改用备用引擎或关键词重试一次；仍失败则缩小时间窗并明确披露。
- 时间窗内证据不足：扩大到 45 天并标注“含临近窗口背景信息”，不得编造。
- 来源相互矛盾：同时列出两方表述与来源，标明无法核实。
- 网页无法访问：退回检索摘要，证据等级降为 C，并在来源表注明“仅摘要”。
- 客户无 ESG 负面信息：写明“本月公开渠道未见重大负面事件”，不推断“不存在”。

## 完成条件

报告含全部 7 个部分、不少于 12 条带链接来源、不少于 3 条时间窗内明确日期、验证脚本通过；报告与中间数据均写入输出目录。
