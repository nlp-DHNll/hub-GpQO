# 共享语料（A/B 两臂共用）

- `esg_intelligence.json`：8 条，已重新编号为 `ESG-S-001`…`ESG-S-008`。
- `manifest.json`：来源文件 sha256、选中条目、原编号、企业/类别/相关性计数、去重警告。

构成（2026-11 运行）：

- 中国神华 4 条（企业动态）
- 中煤能源 2 条（同行实践）
- 政策背景 2 条（政策法规）

使用方式：把 `esg_intelligence.json` 复制到
`output/comparison/run-2026-11/with-scripts/` 与 `no-scripts/`，
两臂 sha256 必须一致。对比脚本会校验。

重新生成：

```bash
python scripts/make_shared_corpus.py \
  --source output/comparison/with-scripts/esg_intelligence.json \
  --source output/comparison/no-scripts/esg_intelligence.json \
  --companies 中国神华 中煤能源 --total 8 \
  --output output/comparison/_shared/esg_intelligence.json
```

注意：语料来自既有实验产物，只做筛选与去重，没有新增事实； `manifest.json`
保留了原 `item_id` 和来源 URL，便于回查。
