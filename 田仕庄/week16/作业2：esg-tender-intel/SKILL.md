---
name: esg-tender-intel
description: This skill should be used when the user asks to 汇总 ESG 招标、查碳盘查 / 碳核查 / 双碳 / 碳中和相关的招标公告、整理招投标清单、做商机清单、看看最近有哪些双碳采购项目，需要一份可溯源、已去重的招投标情报报告 over a time window, 或要每天盯新增 / 按行业口径（能源、制造、金融）筛 / 导出 Word / 推送群消息时。It collects tender notices from Chinese public procurement sources and produces a shortlist with buyer, budget amount, deadline, track classification, and stage (招标 vs 已中标成交).
agent_created: true
---

# ESG 招标情报

从公开渠道检索中国大陆的 ESG / 双碳 / 碳资产相关招标公告，产出**每条可溯源、
金额可核对、赛道可归类、去重可靠**的结构化清单。

## 何时使用

- 「查一下最近有哪些碳盘查的招标」
- 「汇总近三个月双碳相关的采购项目」
- 「整理一份 ESG 咨询的商机清单」
- 「某省属能源集团的碳盘查项目预算是多少」

不适用：需要付费平台内部数据、需要联系人与电话、需要投标文件原文的场景。

## 解释器（先看这条）

本机裸 `python` 指向 WorkBuddy 自带的 Python 3.13，**没装依赖**，直接用会
`ModuleNotFoundError: No module named 'yaml'`。所有命令一律走 conda 环境 `py312`：

```bash
PY="C:/Users/Cooper/miniconda3/envs/py312/python.exe"   # conda env py312 / Python 3.12.13
```

每个代码块第一行都重新定义 `$PY`（shell 变量不跨调用保留）。不要写成
`conda run -n py312 python`：它会重复打印 stderr 并追加一行
`ERROR conda.cli.main_run`，把脚本自己的 `[错误]` 提示淹掉。

## 前置检查

工作目录固定为 skill 根目录（`SKILL.md` 所在目录），所有命令都在这里执行。

```bash
PY="C:/Users/Cooper/miniconda3/envs/py312/python.exe"

# 1. 依赖就绪？缺包时用同一个解释器装："$PY" -m pip install -r requirements.txt
"$PY" -c "import yaml, jinja2, httpx; print('deps ok')"

# 2. 有没有博查 Key？没有 Key 就只能跑离线样本
"$PY" - <<'EOF'
from pathlib import Path
key = Path("config/.env")
print("env file:", key.exists())
if key.exists():
    print("has key:", "BOCHA_API_KEY=sk-" in key.read_text(encoding="utf-8"))
EOF
```

- **有 Key**：直接跑真实检索。
- **没有 Key**：不要卡住。先用 `--provider fixture` 把报告形态跑出来给用户看，
  同时明确告知「当前为离线样本数据」，并请用户提供博查 Key 后再跑真实数据。

## 执行流程

1. **确认范围**。把用户的模糊表述转成四件事：关键词、时间窗口、行业口径、是否只要新增。
   - 「最近」→ 默认 `--days 30`；「近三个月」→ `--days 90`；「今年」→ `--days 365`
   - 「过去两年 / 近两年 / 两年汇总」→ `--days 730 --limit 300`。长窗口会自动
     切成 25 段（每段 30 天）分别检索，报告里会多出「时间趋势」小节
   - 「碳盘查」→ `--query "碳盘查"`；不给关键词 → 省略 `--query`，按
     `config/scope.yaml` 的赛道关键词自动组合
   - 「能源集团 / 制造业 / 上市公司」→ 加 `--preset energy|manufacturing|finance`，
     不要手改 `scope.yaml`（下次升级会被覆盖）
   - 「每天盯新增 / 只要新的」→ 加 `--incremental --only-new`（或直接用
     `scripts/daily.py`）
2. **跑流水线**（见下方命令速查）。
3. **读产出**。报告在 `output/<日期>_<slug>/tender_list.html`（单文件，双击即开），
   同目录还有 `records.json`（结构化，**全量**）与 `run_meta.json`（检索足迹 + 季度趋势）。
   用 `--provider fixture` 演练时目录会带 `_fixture` 后缀，不会覆盖真实报告。
   想把报告给用户看，用 `present_files` 打开这个 html；需要二次加工或转发时加
   `--format md`，要 Word 文档加 `--format docx`，`both` = html+md，`all` = 三种都写。
   窗口超过一个季度时，概览里会多出「时间趋势」表（季度 × 条数 × 金额），
   这是长窗口报告最有价值的部分——讲「两年变化」先讲它，别只念清单。
4. **回复用户**。必须复述关键数字：条数、赛道分布、**阶段分布（几条可投 / 几条已成交）**、
   金额区间与中位数、Top 项目，以及**数据覆盖的缺口**。只说「报告已生成」不算完成任务。

## 命令速查

```bash
PY="C:/Users/Cooper/miniconda3/envs/py312/python.exe"

# 自动组合关键词，近 30 天（最常用）
"$PY" scripts/tender.py --days 30

# 指定关键词，近 90 天
"$PY" scripts/tender.py --query "碳盘查,碳核查,碳足迹" --days 90

# 无 Key 时验证全链路（离线样本，非真实数据）
"$PY" scripts/tender.py --provider fixture --days 30

# 只保留高相关，最多 20 条
"$PY" scripts/tender.py --days 30 --min-relevance 0.85 --limit 20

# 只要「还能投」的项目：招标阶段 + 有预算
"$PY" scripts/tender.py --days 30 --stage tender

# 行业口径（能源 / 制造 / 金融上市公司）
"$PY" scripts/tender.py --days 90 --preset energy

# 多源定向：按 config/sources.yaml 追加 site: 检索 + 列表页抓取
"$PY" scripts/tender.py --days 7 --sources

# 增量：只输出本期新增，同时写库；--notify 推送（密钥读环境变量）
"$PY" scripts/tender.py --days 2 --incremental --only-new --notify webhook

# 每日监控入口（自带增量默认值，供 cron 用）
"$PY" scripts/daily.py
```

常用参数：`--days`（回溯天数）、`--query`（逗号分隔）、`--limit`（清单展示条数上限）、
`--format`（`html` 默认 / `md` / `docx` / `both` / `all`）、`--min-relevance`（覆盖赛道阈值）、
`--stage`（`tender` 只要招标中）、`--preset`（行业预设）、`--sources`（多源定向）、
`--incremental` / `--only-new` / `--db`（已推送库）、`--notify webhook|email`、
`--no-cache`（强制重新检索）、`--print-json`（额外输出机器可读摘要）。
`--list-presets` 列出可用预设。全部参数见 `--help`。

`--days` 超过 31 天时会**按 30 天切片检索**（博查的 `freshness` 接受
`YYYY-MM-DD..YYYY-MM-DD` 闭区间）。原因见下文「解读结果」第 1 条：把两年塞进
一次检索，返回的 top-50 会稀疏撒在 24 个月里，等于对时间轴均匀采样。

**成本**：请求数 = query 条数 × 切片数。`--days 730` 是 13 × 25 = 325 次，串行
约 3 分钟；结果按 `(query, 切片)` 落缓存 24 小时，同一天复跑不再计费。短窗口
（≤31 天）只有 13 次，日常用不受影响。`--sources` 会再加最多 4 条
`site:` 定向 query（`sources.yaml` 的 `max_site_queries`），成本对使用者可见。

退出码：`0` 有结果；`2` 无结果或配置错误（此时看 stderr 的 `[错误]` 行）。
`--only-new` 模式下「没有新增」也返回 `0`——否则 cron 每天都会把「今天没新项目」
当成失败来报警。

### 增量与推送（做日报/监控时用）

- 状态存在 `data/tenders.db`（SQLite，可 `--db` 指定，`--no-store` 完全不碰）。
  只有加了 `--incremental` / `--only-new` / `--notify` 才写库，一次性出报告不会
  留副作用。
- 「新增」= 指纹与归一化标题都没入过库。同一条公告后补了中标金额会变指纹，
  但标题没变，仍算「见过」——宁可少报新增，不要把旧项目当新闻推给用户。
- 推送两个通道：`--notify webhook`（企业微信 / 飞书 / 钉钉，按域名自动适配
  payload）与 `--notify email`（SMTP）。地址与密码**只从环境变量或
  `config/.env` 读**，不要写进命令行。先 `--notify-dry-run` 看内容再真发。
- 推送成功才把记录标记为「已推送」；失败不标记，下次运行会重发。
- 定时任务模板在 `deploy/`（crontab 与 GitHub Actions）。

### 多源定向（`config/sources.yaml`）

默认关闭。加 `--sources` 后：

- `mode: search_site`：把 `site:域名` 追加到检索词，圈定白名单站点。实测
  `--days 7 --sources` 时保留的 5 条里 4 条来自剑鱼标讯——通用检索漏掉的省市级
  项目能被这条捞回来，是提高召回性价比最高的一档。
- `mode: crawl`：抓列表页 HTML，只取锚文本命中关键词的链接，遵循 `robots.txt`，
  每源最多 1 页、间隔 1 秒。**只对静态列表页有效**，JS 渲染站点抓回来是空壳；
  抓不到正文，所以这类记录的发布日期为空（计入「无发布日期但保留」），绝不编造。
- `enabled: false` 的源即使加了 `--sources` 也不跑（表示「明确不要」）。

## 硬约束（不可违反）

1. **不虚构**。报告里每一条都必须有可点击的 `source.url`。检索失败就在
   「数据覆盖与缺口」里如实写，绝不用估算值或想象的项目填充。
2. **不采集个人信息**。联系人姓名、手机、邮箱一律不入库、不进报告。若检索结果
   里出现，忽略即可，不要抄进清单。
3. **不绕过登录 / 验证码 / 付费墙**。只取公开摘要；被拦就换 `site:` 检索或放弃该源。
4. **空项目编号不参与比对**。招标公告普遍没有编号，把空串当相等会让所有无编号
   项目互判重复、只剩一条。这条已在 `esgtender/dedup.py` 里硬编码，不要绕过。
5. **疑似重复只标记、不合并**。标题相似度 ≥ 0.90 的记录保留在清单里并进
   「疑似重复待核实」，由人判断。
6. **金额统一为「元」**。报告展示时折算成万元／亿元，但 `records.json` 里一律是元。
7. **非采购内容不入库**。研报、行业新闻、债券上市公告、补助公示一律不进清单，
   由 `triage.is_tender_intent()` 在分类前拦掉。改 `scope.yaml` 时不要把
   `intent.require_any` 清空，否则整条闸门失效。
8. **同一项目的多阶段公告合并为一条**。同一项目先发「竞争性谈判公告」、后发
   「成交结果公告」时，归一化标题相同 → 指纹相同 → 合并，并把后到记录的成交
   金额补进保留记录。不要为了「保留原始条数」去关掉这条。
9. **密钥只从环境变量 / `config/.env` 读**。Webhook 地址与 SMTP 密码不进命令行、
   不进报告、不进日志（`notify` 结果里只记 host）。推送失败要在 stderr 明示，
   不能静默吞掉。
10. **不伪造发布日期**。列表页抓取（`crawl`）拿不到发布时间就留空，计入
    「无发布日期但保留」；填「今天」会让窗口过滤形同虚设。
11. **已推送库只存摘要索引**。`data/tenders.db` 存标题、采购方、金额、赛道、阶段
    与时间戳，不存摘要正文、不存联系人。它不是原文存档，回查靠 `source.url`。

## 解读结果时常见的七个坑

1. **条数少是正常的，先看漏斗**。真实一次运行（2026-11，`--days 30`）：
   635 次命中 → 428 个不同页面 → **非采购剔除 93** → 低于阈值 320 → 保留 14。
   两年窗口（`--days 730`）：16204 次命中 → 10934 个页面 → 非采购剔除 2617 →
   低于阈值 7465 → 保留 747。想看被挡掉的原因，看 `records.json` 与「非采购内容
   剔除」这一行。
   **窗口必须切片，不能靠放大时间参数**：单用 `oneYear` 或把两年塞进一次区间，
   返回条数不增反降，且近端项目会被旧页面挤出榜单。切片后每月都有数据
   （2024-11 起 24 个月连续覆盖），不切片时 2025 全年一条都没有。
2. **`相关度` 是关键词打分，不是人工判断**。核心／扩展赛道必须标题命中关键词
   才能过线（0.6／0.65），只看摘要命中的会落在灰区并标记「待复核」。展示时
   不要把它说成「匹配度」或「中标概率」。
3. **`N/A` 是真实缺失，不要替用户推断**。特别是截止日期：只认「投标截止时间」
   「报价截止时间」这类锚点，检索摘要里没有就记 `N/A`。早期版本用裸日期兜底，
   结果 24/25 条都「有截止日期」，实际是发布日期——宁可空着。
4. **金额合计与中位数要一起看**。两年窗口 154 条有金额，中位数 35 万，合计
   9.59 亿——合计被十几条「绿色园区基建 / 平台建设」这类大包拉高，不代表咨询
   服务的单价水平。讲趋势时用中位数，讲规模时才用合计。
5. **金额只认预算语境**。有「预算金额／最高限价／中标金额」锚点才算，且排除
   单价（`元/吨`）与超过 20 亿的数字（债券规模、行业总额、累计成交额）。多数记录
   金额是 `N/A`，这是诚实的结果，不是抽取失败。
6. **「中标成交」不是商机**。真实 30 天窗口 14 条里 10 条招标、4 条已定标
   （实测：山东中烟碳足迹项目 1.49 万、南通碳达峰培训 10.52 万都是**成交价**）。
   用户问「有哪些机会」时先看 `stats.tender_count`，或直接加 `--stage tender`；
   讲价格水平才用成交金额，且要说明它是历史成交价而非报价参考。
7. **「新增」条数取决于库的状态**。第一次带 `--incremental` 跑，全部都是新增；
   库里的记录只要标题还出现在窗口内，下次就是「已见」。跨机器 / 换了 `--db`
   会重新计一次新增，不要把它当业务增长。

## 什么内容会被挡掉（`config/scope.yaml` 的 `intent` 段）

主题相关 ≠ 采购公告。真实检索里这些都会命中赛道关键词，但已配置为剔除：

| 被剔除的内容 | 命中原因 | 判定依据 |
|---|---|---|
| 券商研报、行业点评 | 标题含「绿色债券」「碳达峰」 | `deny_any`: 研报 / 点评 |
| 绿色债券上市、发行、付息公告 | 同上 | `deny_any`: 债券上市 / 发行完毕 / 付息 / 申购 |
| 行业快讯、政策解读 | 同上 | `deny_any`: 快讯 / 政策解读 |
| 政策征求意见稿 | 含「实施方案」「公告」，但无采购行为 | `deny_any`: 征求意见 |
| 财政补助、奖补公示 | 同上 | `deny_any`: 补助 / 奖补 |
| 公司官网首页 | 导航区有「招标采购」 | 标题无赛道关键词，不看正文兜底 |

要放宽或收紧，改 yaml 即可，不用动代码。注意 `deny_any` 只匹配**标题**——
正文里出现「政策」「解读」太常见，据此判断会大面积误杀。

## 参考文件

| 文件 | 何时读 |
|---|---|
| `references/schema.md` | 需要按字段消费 `records.json` / `run_meta.json`，或要改字段契约、已推送库表结构时 |
| `config/scope.yaml` | 要增删赛道、关键词、金额分档、阈值时（唯一真源，改这里不用改代码） |
| `config/presets/*.yaml` | 要按行业口径跑时用 `--preset`；新增行业就加一个 yaml，不要改主配置 |
| `config/sources.yaml` | 要加白名单站点或调 `site:` 定向条数时（`--sources` 才生效） |
| `deploy/` | 要挂 cron / GitHub Actions 做每日增量时 |
| `templates/tender_list.html.j2` | 要调整报告版式时（默认格式；`md.j2` 是同构的 Markdown 版，`docx` 由 `esgtender/docx_export.py` 直接生成） |
| `templates/_macros.j2` | 要加/改「新增」「阶段」「已中标」这类徽标时——判断只写在这里，两套模板共用 |
| `esgtender/env.py` | 要加新的推送通道或配置项时：`ALLOWED_KEYS` 加一行，别在别处解析 `.env` |
| `esgtender/netguard.py` | 要新增任何出站请求时：走 `safe_get` / `assert_public_url`，不要直接 `httpx.get` |

## 已知边界

- 只覆盖中国大陆公开渠道；境外项目、需登录的采购系统不在范围。
- 检索质量取决于博查的召回能力，历史窗口越长召回率越低。
- `crawl` 档位只适合静态列表页：不执行 JS、不破验证码、不跟随站外链接，因此
  多数省级交易中心（前端渲染）抓不到内容，这类源请改用 `search_site`。
- docx 导出是「标题 + 表格」的纯排版，不含图表（条形图只在 HTML 里有）。
- 已推送库是单机 SQLite；多机并行跑需要各自一份库，跨机去重不在支持范围。
- 出站请求只放行公网 http(s)：`netguard` 会在每一跳校验解析出的 IP，
  内网 / 环回 / 云元数据地址（169.254.169.254 等）一律拒绝。若你要抓内网站点，
  必须显式改 `netguard` 的白名单，而不是关掉校验。
- 配置只读 `esgtender/env.py` 白名单里的键；环境变量里其它值（`GITHUB_TOKEN` 等）
  不会进入任何返回值，也不该写进日志或 `run_meta.json`。
- 阶段判定读的是**原始标题**：先认站点打的体裁标签（`【招标结果】` → 已成交），
  再剥掉栏目标签（`【招标信用】`）与站点尾巴（`-山西招标网`）后按正文判。
  标题完全不含体裁词的记录会落「其他」，宁可标不出也不猜（比如「XX 公司碳资产
  管理服务」这种服务介绍页，摘要里没有采购信号）。
- `--provider fixture` 是演练模式：不显式给 `--db` 时增量库自动切到
  `data/tenders_fixture.db`，不会污染 `data/tenders.db` 里的真实「往期已见」。
- 参数组合有硬校验，报错即退出码 `2`：`--only-new` 必须配库（不能同时 `--no-store`），
  `--count` 不得超博查上限 50。`--max-queries` 是**总请求数**上限，`--sources`
  追加的 `site:` query 也算在内（先给定向源留位，再截断自动关键词并打印截断明细）。
- 推送结果（`ok` / 失败原因 / 标记条数）落在 `run_meta.json` 的 `meta.notify`；
  推送失败不会中断出报告，也**不会自动补推**——那批记录已经入库，下轮按「往期已见」
  处理，要重发请手动重跑一次，或直接转发 `tender_list.html`。
- 金额、阶段、条形宽度等展示值只在 `render.py` 算一次：`fmt_amount` / `with_pct` /
  `build_stats` 是网页、Markdown、Word、推送共用的唯一实现，不要在别处再抄一份。
