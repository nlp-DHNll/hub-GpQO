# 2026-11 月报质量 A/B 运行目录

两臂已放入同一份 8 条共享语料，sha256 一致。接下来：

1. `with-scripts/` 用 `esg-monthly-report-generator` 生成 `monthly_report.md`；
   `no-scripts/` 用 `esg-monthly-report-generator-noscript` 生成 `monthly_report.md`。
   两臂都不得重新联网检索。
2. 月报末尾附 `附录 A：事实证据台账` 与 `附录 B：行动计划台账`，列名见 `experiment.md` 第 4 节。
3. 把 `token_usage.template.json` 复制为各自目录的 `token_usage.json` 并填写（结构见 `experiment.md` 第 5 节）。
4. 运行：
   ```bash
   python scripts/compare_skill_variants.py \
     --arm-a output/comparison/run-2026-11/with-scripts \
     --arm-b output/comparison/run-2026-11/no-scripts \
     --month 2026-11 --as-of 2026-11-30 \
     -o output/comparison/comparison_metrics.json
   ```
5. 盲评与人工抽查按 `experiment.md` 第 6–7 节执行。

每臂 1 份月报，共 2 份；以中国神华为目标企业，中煤能源放在"同行实践与对标"部分。正文 ≤2500 个汉字（不含标点与附录表）。
