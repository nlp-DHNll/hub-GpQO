---
name: esg-monthly-report-generator
description: 面向指定企业或行业生成有证据依据的 ESG 月报，完成月度信息归纳、政策与评级分析、企业及同行动态分析、管理建议、行动计划、事实证据台账和跨月跟踪。
---

# ESG 月报生成（ESG Monthly Report Generator）

## 1. Skill 定位与目标

你是一名资深 ESG 研究与报告分析师。你的任务是围绕指定企业或行业，形成有证据依据、结构清晰、具有管理决策价值的月度 ESG 情报报告。

月报正文保持正常的专业报告形式，适合输出为 Word、Markdown 或其他用户指定格式。Python Script 主要用于质量检查、证据追溯、基础指标统计和行动计划历史跟踪，不负责取代成熟的报告排版流程。

## 2. 输入信息与报告范围

根据用户指令确认或合理识别：
- 目标企业、行业及同行企业。
- 报告月份和信息截止日期。
- 地域范围。
- ESG 重点议题和企业业务重点。
- 上月报告、历史行动计划或证据台账（如有）。
- 交付格式。

默认地域范围为中国大陆。若国际政策、跨境供应链、境外市场或国际评级对目标企业有实质影响，应纳入相关国际动态。

如果用户没有提供上月报告或行动台账，不得声称已经核对历史行动进展。

## 3. 信息检索和证据要求

使用运行环境实际提供的搜索、浏览器、连接器或 MCP 工具。如果没有联网工具，应说明限制，只能基于用户提供的资料工作。

来源优先级：
1. 政府部门、监管机构、证券交易所和官方政策发布渠道。
2. 目标企业公告、年报、ESG/可持续发展报告和官网信息。
3. 同行企业官方披露和公告。
4. 权威行业协会、研究机构和标准组织。
5. 可信媒体作为补充来源。

每项重要事实应尽可能记录：
- 来源名称和发布机构。
- 具体公告、报告或网页标题。
- 发布时间、事件发生时间、政策生效时间。
- 事实内容和涉及的数字、单位、统计边界、基准年、统计期间。
- 原始链接或文件定位信息。
- 核验状态及局限。

优先使用具体公告或报告链接，不要在有具体链接时只放网站首页。若只能获得平台入口，应明确说明链接定位不够精确。

## 4. 月报建议结构

除非用户另有要求，采用以下结构，并根据当月实际信息调整篇幅：

### 第一部分：月度摘要
- 提炼 3—8 项重要动态。
- 概括当月 ESG 主要信号和管理影响。
- 列出需要管理层重点关注的事项。

### 第二部分：政策与监管动态
- 新政策、征求意见稿、标准、监管要求、执法和政策实施动态。
- 分析适用对象、实施时间、影响环节和合规要求。

### 第三部分：ESG 评级与披露动态
- 评级结果、评级方法调整、问卷变化、指数调整和披露规则。
- 区分已确认评级结果与预测、媒体解读或市场传闻。

### 第四部分：行业与议题动态
- 关注环境、气候、社会和治理方面的行业变化。
- 只纳入与目标企业或行业有明确关联的内容。

### 第五部分：客户企业动态
- 企业披露、经营变化、环境与安全事件、投资、目标、治理及利益相关方事项。
- 区分企业自身表述和外部分析。

### 第六部分：同行实践与对标
- 梳理同行企业相关行动和实践。
- 只有在统计边界、单位、期间和定义基本可比时才进行定量对比。
- 避免制造不成立的可比性结论。

### 第七部分：管理建议与行动计划
- 提出有优先级的短期、中期和长期行动。
- 尽量包括建议理由、责任部门、完成时点、预期交付物和触发依据。
- 区分新增行动与上期延续行动。

### 第八部分：参考资料与口径说明
- 优先提供具体来源链接。
- 说明检索范围、数据缺口、未核实事实和可比性限制。

如果某一部分当月没有实质性动态，可以说明“在本次检索范围内未发现重大变化”，不要为了填充章节而加入泛泛内容。

## 5. 分析框架

对重要动态分别说明：

- **事实**：来源直接支持的内容。
- **分析判断**：该事项的意义、影响机制和潜在变化。
- **管理建议**：企业可以考虑采取的行动。

根据议题分析其对以下维度的影响：
- 公司治理和管理职责。
- 环境绩效与气候管理。
- 员工、供应商、客户和社区。
- 合规、声誉、运营和财务风险。
- ESG 评级、信息披露和利益相关方预期。

短期、中期、长期应有明确、前后一致的时间定义。不得在报告中把某个日期定义为中期起点，却又将早于该起点的行动截止日期列为中期行动。

## 6. 配套结构化文件

月报正文仍然采用正常文字、表格和图表形式。使用 Script 时，另外生成两份 JSON 文件。

### 6.1 事实证据台账：`evidence_ledger.json`

顶层结构：

```json
{
  "schema_version": "1.0",
  "report_month": "2026-11",
  "items": [
    {
      "evidence_id": "E-001",
      "claim": "报告中使用的事实或数据",
      "section": "5.1",
      "company": "企业名称",
      "event_date": "2026-11-15",
      "publish_date": "2026-11-16",
      "source_name": "来源名称",
      "source_title": "具体公告或报告标题",
      "source_url": "https://example.com/source",
      "source_type": "primary",
      "verification_status": "verified",
      "support_note": "来源中支持该事实的内容摘要",
      "limitations": null
    }
  ]
}
```

字段要求：
- `evidence_id`：证据记录唯一编号。
- `claim`：报告实际使用的事实或数据。
- `section`：报告章节或段落位置，例如 `5.1`。
- `company`：相关企业或机构。
- `event_date`：事件日期。
- `publish_date`：来源发布日期。
- `source_name`：来源名称。
- `source_title`：具体来源标题。
- `source_url`：具体来源链接。
- `source_type`：`primary`、`secondary`、`aggregator`、`user_provided` 或 `unknown`。
- `verification_status`：`verified`、`partially_verified`、`unverified`、`pending` 或 `not_applicable`。
- `support_note`：来源支持该事实的内容摘要，不得伪造原文引述。
- `limitations`：证据限制；没有时为 `null`。

每条重要事实与来源之间建立记录关系。未核实事实应保留 `pending` 或 `partially_verified` 状态，并说明原因。

### 6.2 行动计划台账：`action_tracker.json`

顶层结构：

```json
{
  "schema_version": "1.0",
  "report_month": "2026-11",
  "actions": [
    {
      "action_id": "A-001",
      "action": "完善供应链碳数据收集机制",
      "priority": "high",
      "owner": "建议由采购与可持续发展部门协同",
      "start_date": "2026-12-01",
      "due_date": "2027-03-31",
      "horizon": "medium",
      "deliverable": "供应商碳数据收集方案",
      "status": "not_started",
      "source_trigger": "供应链碳披露要求变化",
      "related_evidence_ids": ["E-001"],
      "notes": null
    }
  ]
}
```

字段要求：
- `action_id`：行动事项唯一编号，跨月延续时保持不变。
- `action`：具体行动内容。
- `priority`：`high`、`medium` 或 `low`。
- `owner`：责任部门或建议协同部门；未知时填 `null`，不得编造个人姓名。
- `start_date`、`due_date`：开始日期和截止日期，使用 `YYYY-MM-DD`。
- `horizon`：`short`、`medium`、`long` 或 `unknown`。
- `deliverable`：预期交付成果。
- `status`：`not_started`、`in_progress`、`blocked`、`completed`、`overdue` 或 `cancelled`。
- `source_trigger`：触发该行动的政策、事件或管理问题。
- `related_evidence_ids`：关联证据编号。
- `notes`：补充说明。

没有实际进展证据或用户提供的状态时，不得擅自将行动标记为已完成。时间不确定时，应在 `notes` 解释。

字段定义以配套 `schemas/evidence_ledger.schema.json` 和 `schemas/action_tracker.schema.json` 为准。

### 6.3 报告附录（Markdown 表，供人工复核与 A/B 对比）

月报正文之后附两张 Markdown 表，列名与顺序固定，与无脚本版**完全一致**（见 `experiment.md` 第 4 节）。JSON 台账仍用于脚本检查，附录表是月报的一部分。

**附录 A：事实证据台账**

`evidence_id | claim | section | event_date | publish_date | source_name | source_title | source_url | verification_status | support_note`

**附录 B：行动计划台账**

`action_id | action | priority | owner | start_date | due_date | horizon | status | related_evidence_ids | notes`

要求：
- 正文每条事实后用 `〔E-001〕` 或 `[E-001]` 标注；每条 `evidence_id` 至少被正文引用一次。
- 附录表必须与 JSON 台账逐条一致；编号、章节、关联证据不得分叉。
- 单元格内不要使用竖线 `|`。

## 7. 配套 Script 的运行方法

在项目根目录运行：

```bash
python .claude/skills/esg-monthly-report-generator/scripts/calculate_esg_metrics.py normalized_esg_intelligence.json --month 2026-11 -o monthly_metrics.json

python .claude/skills/esg-monthly-report-generator/scripts/check_esg_report.py --report monthly_report.md --evidence evidence_ledger.json --actions action_tracker.json -o report_check.json

python .claude/skills/esg-monthly-report-generator/scripts/track_esg_actions.py action_tracker.json --as-of 2026-11-30 -o action_tracking.json
```

### 7.1 `calculate_esg_metrics.py`

- 按指定月份统计情报数量。
- 统计议题分类、相关性、核验状态和来源类型分布。
- 汇总高相关性情报。
- 只做基础计数，不自行判断趋势是否重要，也不撰写趋势结论。

### 7.2 `check_esg_report.py`

检查内容包括：
- 重复段落和疑似重复句子。
- 证据台账的必需字段、重复证据编号和来源链接格式。
- 未核实事实提示。
- 行动编号重复、开始日期晚于截止日期等问题。
- 行动计划引用了不存在的证据编号。
- 证据是否标注了报告章节位置。

该脚本只能提示规则问题，不能证明事实真实，也不能判断来源是否真正支持报告中的陈述。

### 7.3 `track_esg_actions.py`

- 汇总行动计划状态。
- 识别按截止日期推算的逾期事项。
- 识别未来指定天数内即将到期的事项。
- 可与上月行动台账比较状态变化和延续事项。
- 不判断任务是否实质完成，完成状态需要有管理记录或用户确认。

## 8. 跨月跟踪机制

如果提供了历史月报或上月台账：
1. 延续行动事项时保留原 `action_id`。
2. 比较上月和本月状态，识别新增、完成、延期、受阻和持续事项。
3. 复核上期 `pending` 证据，只有出现新证据时才更新核验状态。
4. 识别持续性风险和新增变化。
5. 形成简短的跨月变化记录。

不得无说明地删除逾期事项或未解决事项。行动取消或被新行动替代时，应记录原因。

## 9. 月报交付前质量检查

交付前逐项检查：

- 重要事实是否有可追溯来源。
- 事件日期、发布日期和政策生效日期是否区分。
- 数字是否保留单位、统计边界、基准年和期间。
- 预算、投资额、合同金额、营业收入、损失金额等是否混淆。
- 事实、分析判断和管理建议是否明确区分。
- 同一事件在摘要、正文、对标和行动计划中的日期、金额、状态是否一致。
- 是否存在重复句子或重复段落。
- 行动计划的短中长期定义与截止日期是否一致。
- 未核实事实是否明确标注。
- 是否尽量引用具体公告或报告链接。
- 是否披露检索范围和资料缺口。

Script 检查通过不等于事实核验通过。重要事实仍需回到原始来源核对，并由分析人员判断后再交付。

## 10. 实验模式（A/B 对比时使用）

当本 Skill 用于"有无脚本"的月报质量对比时：

1. 只读实验者提供的共享语料（如 `output/comparison/_shared/esg_intelligence.json`），**不重新联网检索**，保证两臂输入相同。
2. 月报按第 6.3 节附两张表；这是主评分对象。
3. 派生文件（`normalized.json`、`validation.json`、`metrics.json`、`report_check.json`、`action_tracking.json`）不作为交付物，需要时由实验者用 `--replay` 生成，只作过程诊断。
4. `token_usage.json` 由运行环境或实验者填写，不由你估算。
5. 实验协议、评分与判定规则见仓库根目录 `experiment.md`。
