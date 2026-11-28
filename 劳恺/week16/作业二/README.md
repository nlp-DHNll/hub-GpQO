# ESG Skills 中文版及配套 Python Scripts

本包包含 4 个中文版 Claude Agent Skills、5 个可运行 Python 脚本、1 个 A/B 对比度量脚本、1 个共享语料筛选脚本和 3 份 JSON Schema。

四个 Skill 均放在 `.claude/skills/`，**仅在本项目内可用**（不会注册到 `~/.claude/skills/`，也不影响其他项目）。

| Skill | 用途 |
|---|---|
| `.claude/skills/esg-intelligence-research/` | 情报检索、来源核验、事实/分析分层、结构化输出（**含脚本**） |
| `.claude/skills/esg-monthly-report-generator/` | 月报结构、证据台账、行动计划、跨月跟踪、交付前检查（**含脚本**） |
| `.claude/skills/esg-intelligence-research-noscript/` | 只交付 Markdown 研究简报，**不产出 JSON** |
| `.claude/skills/esg-monthly-report-generator-noscript/` | 只交付 Markdown 月报（含证据/行动表），**不产出 JSON** |

后两个是**对照实验专用**：交付物与带脚本版同为月报/简报，但不会手工复刻 JSON。做实际业务时用带脚本的那两个。实验协议见 `experiment.md`。

## 运行环境

- Python 3.9+，仅标准库，无需安装第三方依赖。
- 脚本只处理已收集的数据，不负责联网搜索、网页抓取或事实真实性认证。
- 仓库**不附带 `examples/`**；命令中的文件名请换成实际文件。

## 快速运行（有脚本版）

```bash
python .claude/skills/esg-intelligence-research/scripts/normalize_esg_data.py esg_intelligence.json -o normalized.json
python .claude/skills/esg-intelligence-research/scripts/validate_esg_evidence.py normalized.json -o validation.json
python .claude/skills/esg-monthly-report-generator/scripts/calculate_esg_metrics.py normalized.json --month 2026-11 -o metrics.json
python .claude/skills/esg-monthly-report-generator/scripts/check_esg_report.py --report monthly_report.md --evidence evidence_ledger.json --actions action_tracker.json -o report_check.json
python .claude/skills/esg-monthly-report-generator/scripts/track_esg_actions.py action_tracker.json --as-of 2026-11-30 -o action_tracking.json
```

## A/B 对比：月报质量

目标：在**相同情报输入**下，比较带脚本与不带脚本的月报质量。

```bash
# 1) 从既有情报中抽 8 条共享语料（2 家企业 + 政策背景，自动去重）
python scripts/make_shared_corpus.py \
  --source output/comparison/with-scripts/esg_intelligence.json \
  --source output/comparison/no-scripts/esg_intelligence.json \
  --companies 中国神华 中煤能源 --total 8 \
  --output output/comparison/_shared/esg_intelligence.json

# 2) 两臂各自生成 monthly_report.md + token_usage.json 后对比
python scripts/compare_skill_variants.py \
  --arm-a output/comparison/run-2026-11/with-scripts \
  --arm-b output/comparison/run-2026-11/no-scripts \
  --month 2026-11 --as-of 2026-11-30 \
  -o output/comparison/comparison_metrics.json
```

对比脚本主评月报正文与附录 A/B 表：可追溯率、高相关覆盖度、日期纪律、行动表问题、幻造链接、token 消耗；并校验两臂语料 sha256 是否一致。`--replay` 只把配套脚本重跑到 `replay/` 作过程诊断，不参与主评分。

token 由 `token_usage.json` 记录（运行环境 `/cost`、API `usage` 或控制台）；缺失时脚本只给字符估计。盲评结果用 `--judgments output/comparison/judgments.json` 并入；评分、人工抽查与判定规则见 `experiment.md`。

## 文件结构

- `.claude/skills/esg-intelligence-research/`：情报研究 Skill + 标准化/校验脚本。
- `.claude/skills/esg-monthly-report-generator/`：月报 Skill + 指标/检查/跟踪脚本。
- `.claude/skills/*-noscript/`：只交 Markdown 的对照版本。
- `scripts/compare_skill_variants.py`：以月报质量为主对象的 A/B 度量。
- `scripts/make_shared_corpus.py`：从既有情报筛选 8 条共享语料。
- `schemas/`：JSON 字段规范；`experiment.md`：实验协议。
- `output/`：交付与实验产物。

详细字段、调用命令和使用流程见各 `SKILL.md` 与 `experiment.md`。
