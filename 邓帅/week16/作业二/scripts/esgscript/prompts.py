"""固定提示词：筛选（逐页抽取）与总结（起草分析）。措辞固定，同样的页面得到同样口径的字段。"""

from typing import Any

SELECT_MONTHLY_SYSTEM = (
    "你是 ESG 研究助理，为一份 ESG 月报筛选证据。只输出一个 JSON 对象，不要输出任何其它文字。"
)
SELECT_BID_SYSTEM = "你是招投标信息抽取员。只输出一个 JSON 对象，不要输出任何其它文字。"
DRAFT_SYSTEM = "你是资深分析师，为报告起草分析。只输出一个 JSON 对象，不要输出任何其它文字。"

MONTHLY_SECTIONS = ("政策/评级/标准动态", "行业新闻与最佳实践", "客户公司动态", "对标企业动态")
"""证据可以归属的四个章节；待核实事项由渲染时按核实状态自动生成。"""

_BID_FIELDS = """输出这些字段：
- notice_type：tender（招标公告、采购公告、磋商/谈判/询价公告——将要采购）、award（中标/成交/结果公告——已采购）、other（更正、答疑、废标、终止等）
- purchaser：采购人（或招标人）全称；找不到填 null
- region：省级行政区，不带「省」「市」后缀（如 江苏、北京、内蒙古）；找不到填 null
- topic：主题标签。采购内容属于 ESG/双碳专业服务时从六类里选一个：咨询规划、碳排放核算与核查、报告编制与鉴证、碳资产管理与交易、双碳平台与监测系统、培训认证；否则自拟一个简短标签（如 环保工程、设备采购）
- in_scope：true/false。买的是 ESG/双碳专业服务（方案、核算、核查、报告编制与鉴证、碳资产、双碳平台的服务、培训）为 true；买的是工程、施工、设备、货物为 false；软硬件打包时要平台开发服务占主要金额才为 true
- needs_review：范围或类型拿不准时填 true
- published_at：公告页面上的发布日期，写成 YYYY-MM-DD；页面上确实没有就填 null"""


def _page_block(page: dict[str, Any], limit: int) -> str:
    text = page.get("text") or ""
    if text:
        return f"【正文（前 {limit} 字）】\n{text[:limit]}"
    return f"【没有取到正文，只有搜索摘要】\n{page.get('snippet', '')}"


def monthly_select(spec: Any, hit: dict[str, Any], page: dict[str, Any]) -> str:
    """逐页筛选：这一页能否作为月报证据。"""
    days = (spec.window_end - spec.window_start).days + 1
    return "\n".join(
        [
            "【任务】判断下面这一页能否作为 ESG 月报的证据，并抽出需要的字段。",
            f"【客户】{spec.client or ''}　【行业】{spec.industry or ''}",
            f"【时间窗】{spec.window_start} 至 {spec.window_end}（{days} 天）：发布日期落在窗内的才是本期事实。",
            f"【这一页来自哪一路检索】{'、'.join(hit.get('labels') or [])}",
            f"【页面地址】{hit['url']}",
            f"【页面标题】{page.get('title') or hit['title']}",
            f"【代码识别到的发布日期】{page.get('date_hint') or '未知'}",
            _page_block({**page, "snippet": hit.get("snippet", "")}, 4000),
            "",
            "输出这些字段：",
            "- relevant：这一页是否含有一条对客户或其所处行业有意义的 ESG 事实（政策、评级、标准、行业动态、最佳实践、客户或对标企业的行动）。广告、导航页、与客户和行业都无关的泛泛资讯填 false。",
            '- section：所属章节，四选一："政策/评级/标准动态"、"行业新闻与最佳实践"、"客户公司动态"、"对标企业动态"',
            "- is_benchmark：这一页讲的是否是对标企业（与客户同行业、规模相当的其它企业）的行动",
            "- claim：这一页能支撑的一句话结论，陈述一个具体事实（谁、做了什么、数字），不超过 60 字",
            "- quote：从正文中逐字摘录、能直接支撑 claim 的一句原文，不超过 50 个字，不要改写；没有正文时从搜索摘要里逐字摘录",
            "- published_at：页面上的发布日期，写成 YYYY-MM-DD；页面上确实没有就填 null，不要用「N 天前」这类相对时间",
            "- tier：来源可信度分级，1=政府、监管、交易所、国际组织、企业公告与官网；2=主流财经媒体、行业媒体、官方平台的转载或聚合；3=自媒体、营销号",
            "- reason：relevant 为 false，或发布日期在时间窗外时，用一句话说明原因；否则填 null",
        ]
    )


def bid_select(spec: Any, hit: dict[str, Any], page: dict[str, Any], rule: dict[str, Any]) -> str:
    """逐页抽取：一条公告的招标记录字段。"""
    extra = []
    if spec.mode == "monitor":
        extra = [
            "- deadline：投标/响应截止时间，保留原文写法；没有填 null",
            "- summary：一句话摘要（买什么、规模多大），不超过 60 字",
        ]
    return "\n".join(
        [
            "【任务】从下面这一页公告里抽取招标记录的字段。",
            f"【页面地址】{hit['url']}",
            f"【标题】{hit['title']}",
            f"【代码识别到的发布日期】{hit.get('published_at') or page.get('date_hint') or '未知'}",
            f"【代码按标题判断的类型】{rule.get('notice_type', '')}　【代码按关键词判断的主题】{rule.get('topic') or '未命中'}",
            _page_block({**page, "snippet": hit.get("snippet", "")}, 5000),
            "",
            _BID_FIELDS,
            "- amount_text：「中标金额 / 成交金额」在原文中的写法，逐字照抄（如 190万元）；没有中标金额、只有预算或限价、或写法是折扣率/区间时填 null",
            "- winner：中标（成交）人名称；没有填 null",
            *extra,
        ]
    )


def _evidence_lines(evidence: list[dict[str, Any]]) -> str:
    names = {1: "一级", 2: "二级", 3: "三级"}
    return "\n".join(
        f"[{item['id']}] {item['section']} | {item['published_at'] or '日期未知'} | {names[item['credibility_tier']]}"
        f" | {item['claim']} | 摘录：{item['quote']}"
        for item in evidence
    )


def monthly_draft(spec: Any, evidence: list[dict[str, Any]]) -> tuple[str, str]:
    """月报初稿：只有「已核实」的证据交给模型，角标只能取自证据表。"""
    user = "\n".join(
        [
            f"【客户】{spec.client}　【行业】{spec.industry}　【时间窗】{spec.window_start} 至 {spec.window_end}",
            "【证据表】每行一条：[角标] 章节 | 发布日期 | 可信度 | 结论 | 原文摘录",
            _evidence_lines(evidence),
            "",
            "据此起草月报。每条事实的句末加角标 [n]，n 只能是上面证据表里的角标编号；没有证据支撑的话不要写，不要引入证据表以外的事实。",
            "输出这些字段（都是 Markdown 文本）：",
            "- summary：「摘要与本月要点」，4–6 条要点，每条一句，句末带角标",
            "- policy：「政策/评级/标准动态」正文，300–600 字，分「政策」「评级」「标准」三个小标题（### 开头），每条事实带角标；某一类没有证据就写「本期未检索到相关动态」",
            "- industry：「行业新闻与最佳实践」正文，300–600 字，每条事实带角标",
            "- company_facts：「本期公司动态」，列出客户在时间窗内的 ESG 相关动态，每条带角标；没有就写明「本期未检索到客户在窗内的相关动态」",
            "- advice：「影响与建议」，一张 Markdown 表格（序号 | 建议 | 依据），3–6 条针对客户具体情况的建议，依据列写角标",
            "- benchmark_intro：一段话，说明对标企业是按「同行业、规模相当、ESG 披露完善」选出的；本期没有对标企业证据时如实写明",
            '- benchmark：对标企业关键行动对比表的行，JSON 数组，每行 {"company": 企业名, "action": 关键行动（可带角标）, "disclosure": 出自哪份报告或页面, "cites": [角标编号]}；没有对标企业的证据就给空数组',
            "- watchlist：「下月关注清单」，一张 Markdown 表格（序号 | 关注事项 | 关注理由），4–6 条，理由里带角标",
            "- method_notes：两三句，说明本期证据的构成与不足（如某类来源偏少、有多少条仅见摘要）",
        ]
    )
    return DRAFT_SYSTEM, user


def bid_draft(records: list[dict[str, Any]], stats: dict[str, Any]) -> tuple[str, str]:
    """招投标汇总的解读：数字全部来自统计结果，模型只负责解读。"""
    notable = [
        {
            "标题": item["title"][:40],
            "采购人": item["purchaser"],
            "金额": item["amount_text"],
            "主题": item["topic"],
        }
        for item in sorted(
            (record for record in records if record["in_scope"] and record["amount"]),
            key=lambda record: record["amount"] or 0,
            reverse=True,
        )[:12]
    ]
    user = "\n".join(
        [
            "【统计结果】（样本 = 范围内的中标公告；金额单位：元）",
            str(
                {
                    key: stats[key]
                    for key in (
                        "sample_size",
                        "amount_rate",
                        "topic_rank",
                        "amount_distribution",
                        "trend",
                        "purchaser_types",
                        "regions",
                    )
                }
            ),
            f"【金额较高的样本】{notable}",
            "",
            "写一段解读。数字只能用上面统计结果里的，不要估算、不要引入外面的信息；样本不是全量，措辞要写明「样本」。",
            "输出这些字段（都是纯文本，各 1–3 句）：",
            "- opening：总览——哪些主题在放量、金额大致什么量级、金额可得率高不高",
            "- topic_notes：热点主题的解读",
            "- amount_notes：金额分布的解读（多数项目落在哪一档）",
            "- trend_notes：月度趋势的解读（升温还是降温；某段时间样本少要说明可能是检索原因）",
            "- buyer_notes：采购人类型与地区的解读（去哪里找客户）",
            "- typical_notes：典型项目的解读",
        ]
    )
    return DRAFT_SYSTEM, user


def daily_draft(records: list[dict[str, Any]]) -> tuple[str, str]:
    """日报的「值得优先跟进」：按截止日期近、规模大排序，只陈述记录里有的信息。"""
    lines = [
        f"- {item['title']} | 采购人：{item['purchaser']} | 截止：{item.get('deadline') or '未见'} | 摘要：{item.get('summary')}"
        for item in records
    ]
    user = "\n".join(
        [
            "【今日新增招标】",
            *lines,
            "",
            "输出这些字段：",
            "- highlights：1–3 句，今天新增里哪些值得优先跟进（截止日期近、规模大、与双碳专业服务直接相关），只陈述上面有的信息；新增为空时写一句「今日无新增」",
        ]
    )
    return DRAFT_SYSTEM, user
