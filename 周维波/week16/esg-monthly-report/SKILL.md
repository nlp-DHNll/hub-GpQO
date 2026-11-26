---
name: esg-monthly-report
description: "ESG 月度报告生成 Skill：自主联网检索并筛选政策/评级/标准动态、所属行业新闻与最佳实践、客户公司 ESG 动态及对标企业关键行动，按固定口径形成结构化 ESG 月报。当用户要求生成 ESG 月报、可持续发展月报、ESG 动态汇总、企业 ESG 跟踪报告，或以某家上市公司（如中国神华等能源/煤炭企业）为例梳理月度 ESG 表现、合规影响与改进建议时使用。"
---

# ESG 月报生成

## Overview
围绕指定客户主体与报告期，分三条线索自主检索互联网信息，经确定性脚本完成去重、分类、时效过滤与打分后，按固定章节产出 ESG 月报 Markdown 报告；政策合规研判、行业最佳实践提炼、公司影响分析与行动建议由 Agent 结合素材撰写。

## 工作流

### 1. 明确客户与报告期
- 记录：客户名称、所属行业、上市地/监管口径、报告期起止（默认最近 31 天）、关注议题。
- 缺省案例：中国神华（煤炭/能源），对标中煤能源、陕西煤业。

### 2. 分线索自主检索
优先使用可用的联网搜索与浏览器工具，按 `references/esg-frameworks.md` 的信源清单与关键词矩阵检索：
- **政策线**：披露准则、监管规则、评级方法论、鉴证标准、双碳政策。
- **行业线**：行业规划、技术路线、标杆实践、争议事件、需求侧动态。
- **公司线**：公司公告、官网新闻、ESG/可持续报告、评级变动、获奖与项目进展。
- **对标线**：2~4 家同行同期 ESG 行动，统一维度对照。

每条素材整理为脚本输入字段：`title, date, source, url, category(policy|industry|company|peer), summary, tags, relevance, entity`。检索与筛选要求见 `references/esg-frameworks.md`。

### 3. 确定性清洗与打分
将素材保存为 JSON 后运行（脚本仅做后处理，不替代检索）：

```bash
python scripts/collect_signals.py --input signals.json --out cleaned.json \
  --start <YYYY-MM-DD> --end <YYYY-MM-DD> --industry 煤炭 煤电 煤化工 新能源 绿色矿山
```

脚本完成：窗口时效过滤、URL/标题去重、分类兜底与校验、可解释打分（相关性 0.6 + 时效 0.2 + 权威源 0.1 + 行业命中 0.1），并输出分类计数与丢弃原因。

### 4. 生成月报骨架并撰写分析
```bash
python scripts/build_monthly_report.py --input cleaned.json --out report.md \
  --client 中国神华 --industry 煤炭 能源
```
在骨架基础上按 `references/report-template.md` 撰写：本月摘要、政策影响研判、行业最佳实践、公司 E/S/G 影响与可落地建议、对标对照表、跟踪事项与信源清单。

### 5. 成稿校验
对照 `references/report-template.md` 硬性要求逐条检查：事实与判断分离、每条事实可溯源、数据口径一致、建议可落地、无臆造数据；政策引用以最新有效版本为准。

## 参考资源
- `references/esg-frameworks.md`：监管/国际/评级信源清单、关键词矩阵、政策时点速查。
- `references/report-template.md`：固定章节、写作规范、对标对照表模板。
- `scripts/collect_signals.py`：信号清洗、去重、分类与打分。
- `scripts/build_monthly_report.py`：月报 Markdown 骨架生成。
- `assets/sample-signals.json`：中国神华案例的真实样例输入（含窗口外条目，用于演示过滤）。
