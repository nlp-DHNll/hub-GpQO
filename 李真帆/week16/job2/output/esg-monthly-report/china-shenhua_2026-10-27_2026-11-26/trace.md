# 过程记录（trace）

作业目录：`D:\develop\workspace\python\bdai\hub-GpQO\李真帆\week16`　客户：中国神华　时间窗：2026-10-27 至 2026-11-26（30 天）　执行日期：2026-11-26

## 1. 检索与抓取概况

- 内置搜索 30 次：`queries.txt` 前 23 条为首轮，后 7 条为补搜（补搜原因见 `search_plan.md`）。搜索结果按批次写在 `raw/batch01.tsv` 至 `raw/batch08.tsv`，合并为 `agent_results.tsv`（180 行，列：query、title、url、published、snippet）。
- 内置网页读取 5 次（上限 8 次）：成功 2 次，失败 3 次，明细见第 5 节。
- 未修改 `scripts/` 下任何文件，未修改 `references/keywords.yaml`。

## 2. 各脚本打印的统计行（原样照抄）

scan.py

```
[scan] 栏目页条目=271 时间窗内且关键词命中=34 输出=job2/output/esg-monthly-report/china-shenhua_2026-10-27_2026-11-26/list_items.jsonl
```

search.py（三次。前两次 agent 合并 TSV 时漏掉了 batch01，第三次才补全；是 agent 失误，不是脚本问题）

```
[search] provider=file 原始条数=120 去重后=118 输出=.../results.jsonl
[search] provider=file 原始条数=162 去重后=157 输出=.../results.jsonl
[search] provider=file 原始条数=180 去重后=171 输出=D:/develop/workspace/python/bdai/hub-GpQO/李真帆/week16/job2/output/esg-monthly-report/china-shenhua_2026-10-27_2026-11-26/results.jsonl
```

fetch.py（三次。第一次按 SKILL.md 用 `--limit 80`，栏目页条目排在搜索结果之后，大部分没抓到；第二、三次把 `--limit` 提到 200，让时间窗内的条目全部抓取）

```
[fetch] 输入=150 抓取成功=69 抓取失败=11 未抓取=70 输出=.../pages.jsonl
[fetch] 输入=188 抓取成功=128 抓取失败=12 未抓取=48 输出=.../pages.jsonl
[fetch] 输入=202 抓取成功=134 抓取失败=14 未抓取=54 输出=D:/develop/workspace/python/bdai/hub-GpQO/李真帆/week16/job2/output/esg-monthly-report/china-shenhua_2026-10-27_2026-11-26/pages.jsonl
```

抓取失败 14 条的原因：SSLError 6、HTTP 403 3、HTTP 404 2、HTTP 404/429/567 各 1、ReadTimeout 1（含 cets.org.cn"2027年度重点排放单位名录公布"、in-en.com"发改委等五部门节能降碳改造"两条相关页面）。

filter.py（三次。第一次按 SKILL.md 默认分值 3；第二次按"调低 --min-score"降到 1；第三次降到 0，因为中国神华运营数据、兖矿能源"提质增效重回报"2.0方案等公司类新闻标题和正文都不含关键词表里的词，分数为 0）

```
[filter] 输入=150 保留=35 剔除=115（未抓到原文 81 条；关键词不足 18 条；重复标题 6 条；列表页或导航页 5 条；时间窗外 5 条）；保留项里时间窗内=26 日期无法确认=9 页面日期与搜索日期不一致=1
[filter] 输入=188 保留=73 剔除=115（未抓到原文 60 条；关键词不足 14 条；常规审批公示 14 条；重复标题 12 条；列表页或导航页 9 条；时间窗外 6 条）；保留项里时间窗内=61 日期无法确认=12 页面日期与搜索日期不一致=1
[filter] 输入=202 保留=76 剔除=126（未抓到原文 68 条；关键词不足 14 条；常规审批公示 14 条；重复标题 12 条；列表页或导航页 11 条；时间窗外 7 条）；保留项里时间窗内=64 日期无法确认=12 页面日期与搜索日期不一致=1
[filter] 输入=202 保留=90 剔除=112（未抓到原文 68 条；常规审批公示 14 条；重复标题 12 条；列表页或导航页 11 条；时间窗外 7 条）；保留项里时间窗内=74 日期无法确认=16 页面日期与搜索日期不一致=1
```

summarize.py（两次，第二次覆盖 cards.jsonl；第一次的结果另存为 cards.run1.jsonl）

```
[summarize] schema=evidence 输入=76 成功=76 失败=0 token（输入 101015，输出 21196）输出=.../cards.jsonl
[summarize] 章节分布：policy 29，rating 14，industry 10，peer 10，company 9，irrelevant 4
[summarize] 相关性分布：medium 34，high 26，low 11，irrelevant 5
[summarize] 失败示例 https://jnzstatic.cs.com.cn/zzb/htmlInfo/2bb9cb4c7a234447b44c6ae17330bfec.html: RuntimeError: 大模型输出解析失败（ValueError: 不是合法的 JSON）
[summarize] schema=evidence 输入=90 成功=89 失败=1 token（输入 119487，输出 22752）输出=D:/develop/workspace/python/bdai/hub-GpQO/李真帆/week16/job2/output/esg-monthly-report/china-shenhua_2026-10-27_2026-11-26/cards.jsonl
[summarize] 章节分布：policy 30，rating 17，peer 13，company 12，industry 11，irrelevant 6
[summarize] 相关性分布：medium 34，high 28，low 20，irrelevant 7
```

大模型 token 合计：输入 220,502，输出 43,948（两次提炼合计 166 次调用，全部花在证据卡提炼上）。

sources.py（cards.jsonl 经第 4 节的人工改动后导出）

```
[sources] 导出 63 条，其中打开过原文 62 条，仅依据摘要 1 条，输出=.../sources.jsonl
```

render.py

```
[render] 来源 37 条，报告=D:/develop/workspace/python/bdai/hub-GpQO/李真帆/week16/job2/output/esg-monthly-report/china-shenhua_2026-10-27_2026-11-26/report.md，HTML=D:/develop/workspace/python/bdai/hub-GpQO/李真帆/week16/job2/output/esg-monthly-report/china-shenhua_2026-10-27_2026-11-26/report.html
```

check_report.py（两次：改稿前、改稿后）

```
[check] 来源 37 条：缺日期 0，重复链接 0，重复标题 0，时间窗内 37/37
[check] 可核验 36 条（97.3%），标题对得上但日期不一致 1 条，标题部分对得上 0 条（需人工看），标题对不上 0 条，页面无法解析 0 条，打不开 0 条
[check] 引用 107 处：悬空 0，未被引用的来源 0；事实单元 66 条，带引用 59 条（89.4%）
[check] 正文 6073 字，表格 7 个；缺失章节：无
[check] 来源 37 条：缺日期 0，重复链接 0，重复标题 0，时间窗内 37/37
[check] 可核验 36 条（97.3%），标题对得上但日期不一致 1 条，标题部分对得上 0 条（需人工看），标题对不上 0 条，页面无法解析 0 条，打不开 0 条
[check] 引用 107 处：悬空 0，未被引用的来源 0；事实单元 66 条，带引用 61 条（92.4%）
[check] 正文 5985 字，表格 7 个；缺失章节：无
```

## 3. 复核结果的处理

- 悬空引用 0、未被引用的来源 0，无需处理。
- "标题对得上但日期不一致" 1 条：S25（证券日报转载的 10 月份主要运营数据公告）。来源日期 2026-11-14 与页面路径 `2026-11/14` 一致，脚本从页面正文里抽到的是无关日期 2026-01-10，属误报，保留。
- 未带引用的 5 个事实单元都在"八、方法与局限"，是过程说明，没有对应来源。
- 第一版正文 6073 字超出 6000 字上限，删去两段次要说明后为 5985 字。

## 4. 人工改动

cards.jsonl（3 处）

| 卡片（URL） | 字段 | 原值 | 改为 | 原因 |
|---|---|---|---|---|
| http://www.csrcare.com/Cultrue/Show?id=4060 | published | 2026-10-26 | 2026-11-17 | 大模型取了正文里证监会标准的发布日期；文章本身的发布日期是 11-17（页面标注），原值会被判为时间窗外 |
| https://www.ggj.gov.cn/tzgg/202611/t20261105_49950.htm | published | 2026-09-29 | 2026-11-05 | 大模型取了文件落款日期；国管局网站 11-05 对外公布，原值会被判为时间窗外 |
| https://jnzstatic.cs.com.cn/...htmlInfo/2bb9cb4c... | 整张卡 | 无 | 用第一次 summarize 的结果 | 第二次提炼时大模型输出不是合法 JSON，脚本记为失败；卡片内容来自同一页面 |

正文里改正的章节和影响等级（cards.jsonl 里的原值未动）

| 来源（旧编号） | 大模型给的 | 正文采用 | 理由 |
|---|---|---|---|
| S16 碳排放交易网"全国碳市场管控边界进一步清晰" | policy / 高 | 政策表 / 中 | 行业网站解读，门槛规则来自既有文件，不是新规 |
| S21 中国能源产业发展网"11月20日收盘价90.34元" | policy / 高 | 行业动态 / 中 | 是行情数据，不是政策 |
| S14 北京日报"296家" | 高 | 中 | 名录扩容对公司是常规事项 |
| S23 Wind ESG 洞察日报 | policy | 评级与标准 | 内容是评级下调和评级机构观点 |
| S34、S35 申万宏源评价体系 | 高 | 中 | 卖方评价体系，不是监管评级 |
| S43 中财网"5家煤炭央企84.4分" | industry / 高 | 评级与标准、行业两处引用 / 中 | 评价结果对客户有参考价值，无直接约束 |
| S48 财闻网"10月商品煤产量" | 高 | 中 | 月度经营数据 |
| S56 国家能源集团蓝皮书案例 | 高 | 中 | 正面认可，无约束力 |

sources.jsonl

- sources.py 导出 63 条，正文只用了 37 条。按 SKILL.md"正文用不到的条目删掉"，删掉 26 条后重新连续编号，正文的引用编号同步替换。新旧编号对照在 `renumber_map.json`，完整导出保留在 `sources.all.jsonl`。
- 未采用的 26 条（旧编号）：栏目页和列表页（S1 矿山安监局信息公开指南页、S2 国资委政策栏目页、S47 新浪公告列表页、S37 CCUS 频道页）；无日期的静态方法页（S25 华证、S27 国证 ESG 数据页）；同一事件的重复报道（S17 绿色矿山名单第三篇、S46 香港会计师公会奖英文版、S31 山西发布会另一篇、S41 绿色矿山研讨会另一篇、S15 和 S42 另两个交易日的碳价快讯）；地域或议题不相关（S9 新疆绿色矿山公示、S4 武汉绿色创变者大会、S5 CBAM 抵扣指南、S10 发改委发布会、S19 国能e招招标计划、S36 绿色矿山期刊目录、S38 中英 CCUS 中心首页、S44 贵阳会议通知）；来源权威不足或信息量低（S28、S45、S26、S33、S55）。

## 5. 原文核对（内置网页读取，共 5 次）

| 次 | 页面 | 结果 | 用途 |
|---|---|---|---|
| 1 | https://www.chinamine-safety.gov.cn/zfxxgk/fdzdgknr/tzgg/202611/t20261110_738892.shtml | 成功 | 核对矿安综函〔2026〕237号：网站 11-10 发布，落款 11 月 4 日，《矿山重大灾害治理关键环节和风险防控重点》是 .doc 附件，未读取。正文按此表述 |
| 2 | http://epaper.zqrb.cn/html/2026-11/14/content_1287875.htm | 失败（fetch failed） | 改为读脚本抓到的正文，公告表格数值未被脚本抽出，数值改用财闻网卡片（S24） |
| 3 | http://www.csrcare.com/Cultrue/Show?id=4060 | 失败（fetch failed） | 改为读脚本抓到的正文，确认 298 项元素和财政部 11-11 发布会的表述 |
| 4 | https://www.nbd.com.cn/articles/2026-11-26/4660296.html | 成功 | 交叉核对董事会决议：选举董事长、H 股发行授权、增资 19.6 亿元，与 S29、S30 一致 |
| 5 | http://www.tanpaifang.com/tanjiaoyi/2026/1117/122288.html | 失败（fetch failed） | 未核对，S9 按"解读文章"处理并降为中影响 |

另从脚本缓存的正文里核对了一处：陕煤集团"矸石充填不升井"在原文中有，第二次提炼的卡片漏掉了，正文按原文写。

## 6. 证据不足与未采信

- 行业章：本期未检索到权威媒体在时间窗内报道的煤矿较大以上事故。云南沟头煤矿"8·18"事故整改评估报告只搜到凤凰网大风号转载，未追溯一手，按检索手册第 5 节不采信。
- 两项 CCUS 国家标准（煤炭工业网 11-16）被 filter.py 判为"列表页或导航页"剔除，未能进卡片。
- 评级章：本期未检索到 MSCI、标普全球、CDP 在时间窗内对中国神华或对标企业的评级调整。MSCI 11 月指数调整文件是成分股名单，与 ESG 评级无关。
- 对标章：淮北矿业没有单独检索（30 次搜索用完）；国际对标企业（Glencore、BHP、Rio Tinto、Anglo American）未检索。山西焦煤没有以公司名义发布的动态，只检索到其所在的山西省属企业集中发布 ESG 报告（S36）。
- 公司章：上交所、港交所公告原件（PDF）未能读取，董事会决议和关联交易进展以公司官网、权威财经媒体的转述为准，正文已注明。

## 7. agent 自身的失误

- 前两次合并 TSV 时只取了 batch01 的表头、漏了它的 18 行数据，导致前两轮 search、fetch、filter 少了 3 条检索式的结果。第三次合并时发现并补全，最终统计以第三次为准。
- 写 search_plan.md 时把"淮北矿业"误写成"淮北能源"，已改。

## 8. SKILL.md 与脚本的问题（按执行顺序）

1. 第 4 步 `fetch.py --limit 80`：输入顺序是先搜索结果、后栏目页条目，上限 80 时 34 条栏目页条目大多排在后面抓不到，而"栏目页是找时间窗内新政策最可靠的办法"。需要调到 200 才抓全，SKILL.md 没有提示。
2. 第 4 步"关键词不足时调低 --min-score"：客户公司自身的运营公告、对标企业的方案发布，标题和正文都不含关键词表里的词，分数为 0，只能降到 0 才进得来。keywords.yaml 的 client_aliases 只用于绕过"常规审批公示"，不参与计分。
3. filter.py 的"列表页或导航页"判定（链接数不少于 25 且链接文字占比不低于 0.5）会误伤新闻站的正文页，两项 CCUS 国家标准的报道就是这样丢的；这个阈值没有参数可调。
4. summarize.py 优先采用大模型给的 published，而不是 fetch.py 已经从页面抽出的日期。本次有 2 张卡的日期被大模型换成了文内提到的文件日期，一张变成窗口前一天、一张变成窗口前一个月，不手改就会被 check_report 判为时间窗外。另外 summarize.py 没有缓存，重跑一次要重新调用全部大模型（第二次 166 次调用里有一张卡失败）。
5. 大模型给的章节和影响等级两次运行不一致：CBAM 解读从 high/高 变成 medium/中，MSCI 指数成分表从 medium/中 变成 low/低，碳价日报被放进 policy，Wind 日报被放进 policy。SKILL.md 要求 agent 复核，这一步不能省。
6. report-template.md 的附录 B、C 和 render.py 冲突：render.py 只要看到正文里有"附录"标题就不再追加来源附录。按模板写"## 附录"会丢掉 A. 信息来源。本次把 B、C 改成"七、检索与筛选说明""八、方法与局限"绕开，但这样它们会被 check_report 计入事实单元，拉低带引用比例（本次 5 条无引用全部来自这里）。
7. SKILL.md 说"正文用不到的条目从 sources.jsonl 里删掉"，没说要不要重新编号。直接删会留下 S1、S4、S9 这样不连续的编号，对客户交付不合适；本次用脚本重新连续编号并同步改正文，SKILL.md 应写明。
8. check_report.py 对转载页的日期判断：S25 页面正文里有一个无关日期 2026-01-10，被判为"日期不一致"。属于误报，但 SKILL.md 对这一类只说"多为转载稿"，没说要怎么处理。
9. 内置网页读取对 http 页面失败率高（3 次 fetch failed 都是 http），脚本自己用 requests 抓同一页面是成功的。SKILL.md 第 6 步的"打开原文核对"应提示优先读 pages.jsonl 里脚本抓到的正文。
