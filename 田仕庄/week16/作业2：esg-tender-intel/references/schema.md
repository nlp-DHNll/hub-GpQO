# 中间 JSON 字段契约（`records.json` / `run_meta.json`）

实现位于 `scripts/tender.py::build_record`。改动本文件前先改代码，两边必须一致。

## 1. `records.json` —— 数组，每项一条招标记录

```json
{
  "id": "a1b2c3d4e5f6",
  "title_norm": "某省属能源集团碳盘查及温室气体排放核算服务采购",
  "fp": "fp_v1:9f2c...",
  "source": {
    "provider": "bocha",
    "query": "碳盘查 招标公告",
    "queries": ["碳盘查 招标公告", "碳核查 招标公告"],
    "site": "中国政府采购网",
    "url": "https://www.ccgp.gov.cn/...",
    "published": "2026-11-18T11:30:00+08:00"
  },
  "raw": {
    "title": "【招标公告】某省属能源集团有限公司碳盘查及温室气体排放核算服务采购公告-宁夏招标网",
    "title_clean": "某省属能源集团有限公司碳盘查及温室气体排放核算服务采购公告",
    "snippet": "项目编号：NYJT-2026-1101。采购人：…预算金额：120万元。"
  },
  "fields": {
    "buyer": {
      "value": "某省属能源集团有限公司",
      "quote": "采购人：某省属能源集团有限公司。",
      "confidence": "high"
    },
    "amount": {
      "value": "1200000.00",
      "quote": "预算金额：120万元。",
      "confidence": "high"
    },
    "amount_cny": "1200000.00",
    "deadline": {
      "value": "2026-12-05",
      "quote": "投标截止时间：2026-12-05。",
      "confidence": "high"
    },
    "project_no": {
      "value": "NYJT-2026-1101",
      "quote": "项目编号：NYJT-2026-1101。",
      "confidence": "high"
    },
    "project_no_norm": "NYJT20261101"
  },
  "track": {
    "group": "core",
    "id": "T5",
    "name": "碳资产",
    "sub": "碳盘查",
    "relevance": 1.0,
    "rule": "kw:碳盘查",
    "hits": {"title": ["碳盘查", "温室气体排放核算"], "body": ["碳盘查"]},
    "threshold": 0.6,
    "decision": "accept"
  },
  "amount_bucket": "100–500万",
  "stage": {
    "code": "tender",
    "label": "招标",
    "rule": "招标公告"
  },
  "flags": {
    "duplicate_of": null,
    "suspect_of": null,
    "needs_review": false,
    "reasons": [],
    "is_new": true,
    "first_seen": "2026-11-23",
    "award": {
      "id": "f0e1d2c3b4a5",
      "url": "https://www.ccgp.gov.cn/...award",
      "title": "【中标公告】某省属能源集团碳盘查服务…",
      "amount_cny": "1180000.00",
      "published": "2026-11-25"
    }
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | `sha1(url + "\|" + raw.title)[:12]`，用于报告里互相引用 |
| `title_norm` | `str` | 归一化标题：小写、去标点空格、繁转简、去「转载/招标公告」类噪声前后缀 |
| `fp` | `str` | 业务指纹 `fp_v1:sha1(title_norm\|buyer_norm\|amount_cny)`；金额缺失时为 `N/A` |
| `source.queries` | `str[]` | 命中该页面的全部 query（同一页面会被多条 query 召回，此处合并） |
| `source.merged_from` | `str[]`（可选） | 仅当本条合并了同项目的其它阶段公告时出现，值为被合并记录的 URL |
| `raw.title` | `str` | provider 返回的原始标题，未被改写 |
| `raw.title_clean` | `str` | 清洗后标题：去「【招标公告】」类前缀、站点尾巴（`-宁夏招标网`）、尾部项目编号。**报告展示与指纹都用它** |
| `fields.*.value` | `str \| null` | 抽取值；抽不到为 `null`，报告里渲染成 `N/A` |
| `fields.*.quote` | `str` | 原文片段，已对齐到分句边界，可直接回查 |
| `fields.*.confidence` | `enum` | `high` / `mid` / `low` / `none` |
| `fields.amount_cny` | `str \| null` | **十进制字符串，单位「元」**。不用 float，避免精度丢失 |
| `fields.project_no_norm` | `str \| null` | 去空格连字符、大写；空值或 `N/A` 时为 `null` |
| `track.group` | `enum` | `core` / `extended` / `edge` / `none` |
| `track.id` | `str` | 核心 `T1`–`T5`；扩展为赛道名；边缘为 `edge` |
| `track.sub` | `str \| null` | 仅 T5 有：碳盘查 / 碳核查 / 碳资产管理 / CCER |
| `track.relevance` | `float` | 0–1，两位小数。算法见 `scripts/triage.py` 顶部注释 |
| `track.rule` | `str` | 命中的规则，如 `kw:碳盘查`、`edge:碳排放+环评` |
| `track.decision` | `enum` | `accept` ≥ 阈值 ／ `gray` 落灰区 ／ `drop` 低于灰区下界 ／ `not_tender` 非采购公告（研报、新闻、债券上市等），被 `intent` 闸门拦下 |
| `flags.duplicate_of` | `str \| null` | 被判重复时，指向保留记录的 `id`（该记录不在 `records.json` 里） |
| `flags.suspect_of` | `str \| null` | 标题相似度 ≥ 0.90 时指向另一条记录，**两条都保留** |
| `flags.needs_review` | `bool` | `decision == "gray"` 时为 `true` |
| `flags.is_new` | `bool`（可选） | 仅在启用已推送库（`--incremental` / `--only-new` / `--notify`）时出现：`fp` 与 `title_norm` 都未入库 |
| `flags.first_seen` | `str`（可选） | 首次入库日期 `YYYY-MM-DD`；往期记录的值为库里保存的原始日期 |
| `flags.award` | `object`（可选） | 该招标项目已关联到中标/成交公告时的摘要：`id` / `url` / `title` / `amount_cny` / `published`。**只标注，不删除中标记录** |
| `flags.awarded_by` | `str`（可选） | 中标记录反向指向对应的招标记录 `id` |
| `stage.code` | `enum` | `tender` 招标 ／ `award` 中标成交 ／ `change` 变更澄清 ／ `other` 未识别。判定只看**原始标题**，见 `extract.parse_stage` |
| `stage.label` | `str` | 展示用中文：招标 / 中标成交 / 变更/澄清 / 其他 |
| `stage.rule` | `str` | 命中的关键词，如 `中标公告`；`other` 时为空串 |
| `flags.reasons` | `str[]` | 去重/疑似判定依据，如 `["fingerprint"]`、`["title_similarity:0.923"]`、`["merged_fields"]`（本条被同项目其它阶段公告补全过字段）、`["award_linked"]` / `["award_amount"]`（中标关联与金额回填） |

## 2. `run_meta.json` —— 本次运行的足迹

```json
{
  "meta": {
    "generated_date": "2026-11-23",
    "generated_at": "2026-11-23 20:55:07",
    "run_id": "20261123-205507",
    "query_label": "自动组合（scope.yaml 关键词）｜预设 能源电力",
    "days": 30,
    "provider": "bocha",
    "raw_hits": 9,
    "raw_hits_total": 25,
    "queries": ["碳盘查 招标公告", "碳核查 招标公告", "碳核查 招标公告 site:ccgp.gov.cn"],
    "freshness_windows": ["2026-10-25..2026-11-23"],
    "failures": [{"query": "CCER 招标公告", "provider": "bocha", "reason": "博查限频：…"}],
    "kept_total": 747,
    "window_total": 747,
    "shown": 300,
    "only_new": false,
    "duplicates": 1,
    "below_threshold": 2,
    "not_tender": 64,
    "stage_filtered": 0,
    "award_links": 12,
    "thresholds": {"core": 0.6, "extended": 0.65, "edge": 0.75},
    "gray_low": 0.2,
    "weights": {"title_base": 0.65, "title_extra": 0.3, "body_bonus": 0.3, "body_saturate": 3},
    "preset": {"name": "energy", "title": "能源电力", "description": "…", "path": "config/presets/energy.yaml"},
    "sources": {
      "path": "config/sources.yaml",
      "configured": 5,
      "enabled": 3,
      "by_mode": {"search_site": 3, "crawl": 2},
      "used": [{"id": "ccgp", "name": "中国政府采购网", "mode": "search_site", "hits": 65,
                "queries": ["碳核查 招标公告 site:ccgp.gov.cn"]}]
    },
    "incremental": {"enabled": true, "new": 14, "seen": 733, "db": "data/tenders.db",
                    "stats": {"total": 820, "oldest": "2025-01-03", "newest": "2026-11-23",
                              "pending": 0, "db": "data/tenders.db"}},
    "notify": {"ok": true, "channel": "webhook", "target": "qyapi.weixin.qq.com",
               "error": "", "marked": 14}
  },
  "stats": {"total": 7, "by_group": [], "by_track": [], "by_bucket": [], "by_stage": [],
            "tender_count": 5, "award_count": 2, "award_sum": "44.80 万元",
            "award_amount_known": 2, "new_count": 7,
            "amount_known": 7, "amount_sum": "120.00 万元", "amount_median": "60.00 万元",
            "amount_unknown": 0, "needs_review": 0, "suspects": 0},
  "trend": [{"label": "2026Q4", "count": 12, "core": 9, "extended": 3, "amount_known": 2,
             "amount_sum": "45.50 万元", "amount_wan": "45.50 万元", "partial": true, "pct": 100.0}],
  "suspects": [{"a": "a1b2c3", "b": "d4e5f6", "similarity": 0.923, "a_title": "…", "b_title": "…"}],
  "dropped_duplicates": [{"id": "x9y8z7", "title": "…", "of": "a1b2c3"}]
}
```

| 字段 | 含义 |
|---|---|
| `raw_hits_total` | provider 返回的原始条数（同一页面被多条 query 召回会重复计数） |
| `raw_hits` | 按 `(title, url)` 合并后的不同页面数 |
| `failures` | 单条 query 失败原因；非空时报告会写进「数据覆盖与缺口」 |
| `below_threshold` | 因相关度不足被丢弃的条数 |
| `not_tender` | 因「不是采购公告」被 `intent` 闸门剔除的条数（研报 / 新闻 / 债券上市 / 补助公示等） |
| `freshness_windows` | 实际发出的时间切片（`YYYY-MM-DD..YYYY-MM-DD` 闭区间）；≤31 天时是 `oneMonth` 这类单词 |
| `kept_total` | 去重后保留的**全量**条数，不随 `--limit` 变；`--only-new` 时是「本期新增」条数 |
| `window_total` | 窗口内的全量条数（不受 `--only-new` 影响）。`kept_total < window_total` 说明本次只输出了新增 |
| `shown` | 报告清单实际展示的条数（= `min(kept_total, --limit)`）；`stats` 与 `trend` 始终基于 `kept_total` |
| `only_new` | 是否启用「只输出本期新增」（`--only-new`） |
| `stage_filtered` | 因 `--stage` 过滤被跳过的条数 |
| `award_links` | 招标—中标关联成功的组数（同一归一化标题下的招标 + 中标配对） |
| `preset` | 行业预设画像 `{name, title, description, path}`；未用 `--preset` 时为 `null` |
| `sources` | 多源画像：`configured` 配置源数、`enabled` 本轮启用数、`by_mode` 各模式数量、`used` 实际产生命中的源（含 `hits` / `queries`）。未加 `--sources` 时为 `null` |
| `incremental` | 已推送库结果：`new` 本期新增、`seen` 往期已见、`db` 库路径、`stats` 库内统计（`total` / `oldest` / `newest` / `pending`）；未启用库时为 `null` |
| `notify` | 推送结果 `{ok, channel, target, error, marked?}`；`target` 只记 host（不回显带 token 的完整 URL）；`marked` 是本次标为「已推送」的条数（覆盖全部新增，不受 `--limit` 截断）；无新增时 `skipped: "no-new"`；**在推送之后才写盘**，所以失败原因一定在文件里 |
| `duplicates` | 因编号/指纹被判重复的条数 |
| `suspects` | 疑似重复对，已保留在 `records.json` 中 |
| `trend` | 按季度升序的聚合：`count` / `core` / `extended` / `amount_known` / `amount_sum`；无发布日期的记录不进趋势（会虚增某季度） |
| `trend[].partial` | 该季度是否被窗口首尾截断（不是完整季度）。为 `true` 时条数天然偏低，报告里打 `*` |
| `trend[].amount_wan` | 同 `amount_sum`，但**固定用万元**。HTML 趋势列用它：一列里混着「3.16 亿元」和「6286.42 万元」没法比大小 |
| `trend[].pct` / `stats.by_track[].pct` / `by_bucket[].pct` | 条形图宽度（0–100，相对同组最大值），只为渲染服务，随时间窗变化，**不要当业务指标**；被排除出分母的行（金额分档的 `N/A`）封顶 100，不代表「占满」 |
| `stats.amount_unknown` | `amount_cny` 为 `null` 的条数。HTML 金额分档排除它算条形宽度，否则真实分档会被压成一条线 |
| `stats.by_stage` | 阶段分布 `{code, label, count, pct, share}`，顺序固定为「招标 → 中标成交 → 变更/澄清 → 其他」（按 `code` 排序，不按数量）；统计以 `code` 为准，`label` 只是展示名 |
| `stats.tender_count` / `award_count` | 招标中（可投）条数 / 已中标成交条数 |
| `stats.award_sum` / `award_amount_known` | 中标成交记录的已知金额合计与条数（成交价是历史价格证据，不是报价参考） |
| `stats.new_count` | 本报告集合内 `flags.is_new == true` 的条数；未启用已推送库时为 0 |

## 3. 不变量（消费方可以依赖）

1. `fields.amount_cny` 若有值，必然是**元**为单位的十进制字符串，可直接 `Decimal()`。
2. `track.relevance ∈ [0, 1]`，且 `decision == "drop"` 的记录**不会**出现在
   `records.json` 里——被丢弃的只在 `run_meta.json` 的 `below_threshold` 计数。
3. `flags.duplicate_of` 非空的记录同样不在 `records.json` 里；它只出现在
   `run_meta.json.dropped_duplicates`。
4. `flags.suspect_of` 非空的两条记录**都在** `records.json` 里，需要人工判断。
5. `records.json` 是**全量**，与 `--limit` 无关；只有报告里的清单（HTML 表格 / Markdown 表格）会被截断。
6. `fields.project_no_norm` 为 `null` 时，该记录不参与编号级去重比对。
7. `raw.title_clean` 恒非空（清洗失败时回退为 `raw.title`），可直接用于展示。
8. `track.decision == "not_tender"` 的记录**不会**出现在 `records.json` 里，只在
   `run_meta.json.not_tender` 计数。
9. `fields.amount.confidence` 只可能是 `high` / `mid` / `none`。`low` 已废弃：
   早期对任意「数字+单位」兜底标 `low`，结果债券规模、配额单价都被当成预算。
10. `stage` 恒存在（`code` ∈ `tender/award/change/other`），`other` 表示标题里没有
    阶段信号，不代表记录无效。
11. `flags.is_new` / `flags.first_seen` 只在启用已推送库时出现。未启用时不要依赖它们。
12. `source.provider == "crawl"` 的记录 `source.published` 恒为空串——列表页没有
    可靠的发布日期，宁可让上层计入 `unknown_date`，也不填「今天」伪造窗口命中。

## 4. 已推送库（`data/tenders.db`）

`scripts/store.py`。**不是存档，是索引**：只存摘要字段与首次/最近出现时间，原文回查
仍靠 `records.json` 与 `source.url`。联系人、电话一律不入库。

```sql
CREATE TABLE records (
    fp          TEXT PRIMARY KEY,   -- 业务指纹，唯一的幂等键
    id          TEXT NOT NULL,
    title       TEXT NOT NULL,
    title_norm  TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL,
    buyer       TEXT,
    amount_cny  TEXT,
    track_id    TEXT,
    track_name  TEXT,
    stage       TEXT,
    published   TEXT,
    first_seen  TEXT NOT NULL,      -- 首次入库日期，跨天不变
    last_seen   TEXT NOT NULL,      -- 本次运行日期
    seen_count  INTEGER NOT NULL DEFAULT 1,
    last_run    TEXT,
    notified_at TEXT                -- 推送成功后写入；NULL = 待推送
);

CREATE TABLE runs (                 -- 每次运行一行，供审计与回溯
    run_id TEXT PRIMARY KEY, started_at TEXT, days INTEGER, provider TEXT,
    query_label TEXT, kept INTEGER, new_count INTEGER, notified INTEGER
);
```

| 行为 | 规则 |
|---|---|
| 写入 | `INSERT … ON CONFLICT(fp) DO UPDATE`：更新 `last_seen` / `seen_count + 1`，不动 `first_seen` 与 `notified_at` |
| 「新增」判定 | `fp` 不在库 **且** `title_norm` 不在库。只按 `fp` 判会把「后补中标金额导致指纹变化」的同一条公告重复报成新增 |
| 推送去重 | 推送成功后 `mark_notified(fps)`；推送失败**不标记**，否则这批新增永远不会再提醒 |
| 清理 | `--prune-days N` 删除 `last_seen` 早于 N 天前的记录，默认两年，与最长窗口对齐 |

## 5. 校验方式

代码在写入前不做 pydantic 强校验（当前版本刻意省掉这个依赖）。若下游要做严格
校验，按上表逐字段断言即可；`tests/test_pipeline.py` 已覆盖金额、日期、编号、
归一化、去重、分类六类边界。
