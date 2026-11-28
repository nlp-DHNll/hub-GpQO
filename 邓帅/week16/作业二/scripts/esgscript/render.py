"""渲染：把结构化数据与分析文字排成 report.md，并核对正文角标能否对上证据表。"""

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .bridge import contract, reportparse
from .ccgp import SOURCE_SITE
from .collect import WORK_DIR, CollectSpec, read_json, search_summary
from .stats import format_amount

TIER_NAMES = {1: "一级", 2: "二级", 3: "三级"}
VERIFICATION_NAMES = {"verified": "已核实", "summary-only": "仅见摘要", "excluded": "已排除"}
_PROSE_KEYS = (
    "summary",
    "policy",
    "industry",
    "company_facts",
    "advice",
    "benchmark_intro",
    "watchlist",
    "method_notes",
)
_NO_EVIDENCE = "本期未检索到相关动态。"


def _cell(value: object) -> str:
    return (
        re.sub(r"\s*\n\s*", " ", str(value if value is not None else "")).replace("|", "\\|").strip() or "—"
    )


def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """Markdown 表格；单元格里的竖线与换行会被转义。"""
    head = f"| {' | '.join(_cell(header) for header in headers)} |"
    return "\n".join(
        [
            head,
            "|" + "---|" * len(headers),
            *(f"| {' | '.join(_cell(cell) for cell in row)} |" for row in rows),
        ]
    )


def _text(analysis: dict[str, Any], key: str, fallback: str = _NO_EVIDENCE) -> str:
    """取一段分析文字。模型偶尔不按约定把一段话写成要点数组或对象，这里都排成 Markdown，不落回占位文字。"""
    value = analysis.get(key)
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, list) and value:
        return "\n".join(
            f"- {item.strip()}" if isinstance(item, str) else f"- {json.dumps(item, ensure_ascii=False)}"
            for item in value
        )
    if isinstance(value, dict) and value:
        return "\n".join(f"- **{name}**：{_text(value, name)}" for name in value)
    return fallback


def _cites(*texts: object) -> list[int]:
    return [
        number
        for text in texts
        for number in reportparse.find_citations(text if isinstance(text, str) else "")
    ]


def _marks(numbers: Sequence[int]) -> str:
    return "".join(f"[{number}]" for number in sorted(set(numbers)))


def _rate(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.0%}（{numerator}/{denominator}）" if denominator else "—"


def _months(spec: CollectSpec) -> int:
    months = (
        (spec.window_end.year - spec.window_start.year) * 12 + spec.window_end.month - spec.window_start.month
    )
    return months + (1 if spec.window_end.day >= spec.window_start.day else 0)


def _chart(charts: Sequence[str], name: str) -> str:
    return next((f"![{name}](.{path})" for path in charts if path.endswith(f"{name}.png")), "")


def _monthly(
    spec: CollectSpec,
    data: dict[str, Any],
    analysis: dict[str, Any],
    stats: dict[str, Any],
    search: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    evidence: list[dict[str, Any]] = data.get("evidence", [])
    ids = [int(item["id"]) for item in evidence]
    benchmark = [row for row in analysis.get("benchmark") or [] if isinstance(row, dict)]
    # 对标表的行先定下来：正文引用了哪些角标，要以实际渲染出来的文字为准
    benchmark_rows: list[list[object]] = []
    for row in benchmark:
        marks = [
            number
            for number in _cites(str(row.get("cites") or ""), str(row.get("action") or ""))
            if number in ids
        ]
        benchmark_rows.append(
            [
                str(row.get("company") or "—"),
                str(row.get("action") or "—"),
                str(row.get("disclosure") or "—"),
                _marks(marks),
            ]
        )
    for peer in spec.peers:
        if not any(peer in str(row.get("company") or "") for row in benchmark):
            benchmark_rows.append([peer, "本次预算内未检索到该企业的披露信息", "—", "—"])
    if not benchmark_rows:
        benchmark_rows.append(["—", "本次未检索到对标企业的披露信息", "—", "—"])
    cited = _cites(
        *(analysis.get(key) for key in _PROSE_KEYS),
        *(str(row[1]) for row in benchmark_rows),
        *(str(row[3]) for row in benchmark_rows),
    )
    unknown = sorted({number for number in cited if number not in ids})
    uncited = sorted(set(ids) - set(cited))
    problems = [f"正文角标在证据表里没有对应记录：{_marks(unknown)}"] if unknown else []
    warnings = [f"有 {len(uncited)} 条证据没被正文引用，已列入「备查证据」"] if uncited else []

    pending = [item for item in evidence if item["verification"] != "verified"]
    pending_table = (
        table(
            ["序号", "事项", "线索来源", "未核实的原因"],
            [
                [
                    index,
                    item["claim"],
                    f"[{item['id']}]",
                    item.get("excluded_reason") or "仅见摘要，没能在原文里逐字核对",
                ]
                for index, item in enumerate(pending, start=1)
            ],
        )
        if pending
        else "本期无待核实事项。"
    )

    verification, tiers = stats["verification"], stats["tiers"]
    zhipu = search.get("zhipu", {})
    done, failed = zhipu.get("ok", 0), zhipu.get("failed", 0)
    verified = verification.get("verified", 0)
    only_summary, excluded = verification.get("summary-only", 0), verification.get("excluded", 0)
    total = stats["evidence_total"]
    overview = (
        f"本次由脚本版流水线生成：检索 {search['total']} 路（智谱搜索 {done} 次成功、{failed} 次失败），"
        f"逐页筛选后登记证据 {total} 条——已核实 {verified} 条、仅见摘要 {only_summary} 条、"
        f"已排除 {excluded} 条。来源构成：一级 {tiers.get(1, 0)} 条、二级 {tiers.get(2, 0)} 条、"
        f"三级 {tiers.get(3, 0)} 条。"
    )
    in_window = _rate(stats["in_window"], total - excluded)
    method = "\n\n".join(
        part
        for part in (
            overview,
            f"发布日期落在时间窗内的占 {in_window}，日期未知 {stats['unknown_date']} 条。",
            "检索词：" + "；".join(search["queries"]) + "。",
            _text(analysis, "method_notes", ""),
            f"未在正文引用的备查证据：{_marks(uncited)}。" if uncited else "",
        )
        if part
    )

    appendix = (
        table(
            ["角标", "所属章节", "支撑的结论", "来源", "发布日期", "原文摘录", "可信度分级", "核实状态"],
            [
                [
                    item["id"],
                    item["section"],
                    item["claim"],
                    f"[{urlparse(item['url']).hostname}]({item['url']})",
                    item.get("published_at") or "未知",
                    item.get("quote") or "—",
                    TIER_NAMES[item["credibility_tier"]],
                    VERIFICATION_NAMES[item["verification"]],
                ]
                for item in evidence
            ],
        )
        if evidence
        else "本期没有登记证据。"
    )

    client = spec.client or "客户"
    parts = [
        f"# {client} ESG 月报（{spec.window_start} 至 {spec.window_end}）",
        f"- 客户：{client}\n- 行业：{spec.industry or '未指定'}\n"
        f"- 时间窗：{spec.window_start} 至 {spec.window_end}（{spec.days} 天）",
        "## 一、摘要与本月要点\n\n" + _text(analysis, "summary", "本期证据不足，暂无要点。"),
        "## 二、政策/评级/标准动态\n\n" + _text(analysis, "policy"),
        "## 三、行业新闻与最佳实践\n\n" + _text(analysis, "industry"),
        f"## 四、{client}公司动态：影响与建议\n\n### 4.1 本期公司动态\n\n" + _text(analysis, "company_facts"),
        "### 4.2 影响与建议\n\n" + _text(analysis, "advice", "本期证据不足，暂不提出建议。"),
        "### 4.3 对标企业关键行动对比表\n\n"
        + _text(analysis, "benchmark_intro", "对标企业按同行业、规模相当、ESG 披露完善的规则选取。")
        + "\n\n"
        + table(["对标企业", "关键行动", "披露情况", "来源"], benchmark_rows),
        "## 五、下月关注清单\n\n" + _text(analysis, "watchlist", "本期证据不足，暂不列关注清单。"),
        "## 六、方法与来源说明\n\n" + method,
        "## 七、待核实事项\n\n" + pending_table,
        "## 八、证据表附录\n\n" + appendix,
    ]
    return "\n\n".join(parts) + "\n", {"problems": problems, "warnings": warnings}


def _bid_summary(
    spec: CollectSpec,
    data: dict[str, Any],
    analysis: dict[str, Any],
    stats: dict[str, Any],
    search: dict[str, Any],
    charts: Sequence[str],
) -> tuple[str, dict[str, Any]]:
    out_of_scope = [item for item in data.get("records", []) if not item.get("in_scope")]
    excluded = [item for item in data.get("records", []) if item.get("verification") == "excluded"]
    period = "季度" if spec.days > 180 else "月份"
    sites = "、".join(f"{name} {count} 条" for name, count in stats["source_sites"].items()) or "—"
    amount_rate = (
        f"{stats['amount_rate']:.0%}（{stats['amount_available']}/{stats['sample_size']}）"
        if stats["amount_rate"] is not None
        else "—"
    )
    parts = [
        f"# ESG 相关招标近 {_months(spec)} 个月汇总（{spec.window_start} 至 {spec.window_end}）",
        f"- 时间窗：{spec.window_start} 至 {spec.window_end}（{_months(spec)} 个月）\n"
        f"- 样本量：{stats['sample_size']} 条范围内中标公告\n- 来源构成：{sites}\n"
        f"- 金额可得率：{amount_rate}",
        _text(analysis, "opening", "本期样本不足，暂不作解读。"),
        "## 一、热点主题排行\n\n"
        + _text(analysis, "topic_notes", "")
        + "\n\n"
        + table(
            ["排名", "主题", "样本数", "中标金额合计", "金额合计覆盖"],
            [
                [
                    index,
                    item["topic"],
                    item["count"],
                    format_amount(item["amount_sum"]) if item["amount_covered"] else "金额不可得",
                    f"{item['amount_covered']}/{item['count']} 条",
                ]
                for index, item in enumerate(stats["topic_rank"], start=1)
            ],
        )
        + "\n\n"
        + _chart(charts, "topic_rank"),
        "## 二、金额分布\n\n"
        + _text(analysis, "amount_notes", "")
        + "\n\n"
        + table(
            ["金额区间", "样本数"], [[item["bucket"], item["count"]] for item in stats["amount_distribution"]]
        )
        + "\n\n"
        + _chart(charts, "amount_distribution"),
        f"## 三、月度趋势（按{period}归并）\n\n"
        + _text(analysis, "trend_notes", "")
        + "\n\n"
        + table(
            [period, "中标公告数", "中标金额合计"],
            [[item["period"], item["count"], format_amount(item["amount_sum"])] for item in stats["trend"]],
        )
        + "\n\n"
        + _chart(charts, "trend"),
        "## 四、采购人类型与地区分布\n\n"
        + _text(analysis, "buyer_notes", "")
        + "\n\n"
        + table(["采购人类型", "样本数"], [[name, count] for name, count in stats["purchaser_types"].items()])
        + "\n\n"
        + _chart(charts, "region")
        + "\n\n"
        + table(["地区", "样本数"], [[name, count] for name, count in stats["regions"].items()]),
        "## 五、典型项目\n\n"
        + _text(analysis, "typical_notes", "")
        + "\n\n"
        + table(
            ["序号", "项目", "采购人", "地区", "中标金额", "中标人", "链接"],
            [
                [
                    index,
                    item["title"],
                    item.get("purchaser") or "—",
                    item.get("region") or "—",
                    format_amount(item["amount"]) if item.get("amount") is not None else "金额不可得",
                    item.get("winner") or "—",
                    f"[公告]({item['url']})",
                ]
                for index, item in enumerate(stats["typical"], start=1)
            ],
        ),
        "## 六、方法与来源说明\n\n"
        + f"本次由脚本版流水线生成。智谱搜索 {search.get('zhipu', {}).get('ok', 0)} 次成功、"
        f"{search.get('zhipu', {}).get('failed', 0)} 次失败；{SOURCE_SITE}站内直连 "
        f"{search.get('ccgp', {}).get('ok', 0)} 次成功、{search.get('ccgp', {}).get('failed', 0)} 次失败。"
        f"登记招标记录 {len(data.get('records', []))} 条。"
        f"其中范围内的中标公告 {stats['sample_size']} 条是样本（含仅见摘要 {stats['summary_only']} 条），"
        f"范围内的招标公告 {stats['in_scope_tender_count']} 条不进样本，"
        f"边界外 {stats['out_of_scope_total']} 条只进附录，"
        f"发布日期落在时间窗外 {stats['excluded_total']} 条不进统计。"
        "金额由脚本按原文写法换算成元，换算不出确定金额的记为不可得。这是样本，不是全量普查；"
        "各省公共资源交易平台的站内检索与付费招投标数据库没有覆盖。",
        "## 附录：边界外招标\n\n"
        + (
            "与 ESG 沾边但不属于专业服务的招标，只作线索列在这里，不进上面的统计。\n\n"
            + table(
                ["序号", "项目", "采购人", "主题", "链接"],
                [
                    [
                        index,
                        item["title"],
                        item.get("purchaser") or "—",
                        item.get("topic") or "—",
                        f"[公告]({item['url']})",
                    ]
                    for index, item in enumerate(out_of_scope, start=1)
                ],
            )
            if out_of_scope
            else "本期没有检索到边界外的招标。"
        )
        + "\n\n### 发布日期落在时间窗外的记录\n\n"
        + (
            table(
                ["序号", "项目", "发布日期", "链接"],
                [
                    [index, item["title"], item.get("published_at") or "—", f"[公告]({item['url']})"]
                    for index, item in enumerate(excluded, start=1)
                ],
            )
            if excluded
            else "没有。"
        ),
    ]
    return "\n\n".join(parts) + "\n", {"problems": [], "warnings": []}


def _daily(
    spec: CollectSpec, data: dict[str, Any], analysis: dict[str, Any], search: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    records: list[dict[str, Any]] = data.get("records", [])
    keywords = "、".join(f"「{text}」" for text in search["keywords"]) or "无"
    queries = "、".join(f"「{text}」" for text in search["queries"][:12]) or "无"
    coverage = (
        f"{SOURCE_SITE}站内直连（{keywords}）；经智谱搜索覆盖的站点不固定（{queries}）。"
        "未覆盖：各省公共资源交易平台的站内检索、付费招投标数据库。"
    )
    parts = [
        f"# ESG 招标监控日报（{spec.window_end}）",
        f"- 基线：{spec.window_start}\n- 时间窗：{spec.window_start} 至 {spec.window_end}\n"
        f"- 新增：{len(records)} 条\n"
        f"- 覆盖范围：{coverage}",
    ]
    highlights = _text(analysis, "highlights", "")
    if highlights:
        parts.append(highlights)
    if records:
        parts.append(
            "## 新增招标公告\n\n"
            + "\n\n".join(
                f"### {index}. {item['title']}\n\n- 采购人：{item.get('purchaser') or '未写明'}\n"
                f"- 发布日期：{item.get('published_at') or '未知'}\n"
                f"- 截止日期：{item.get('deadline') or '未见'}\n"
                f"- 链接：{item['url']}\n- 摘要：{item.get('summary') or '（无）'}"
                for index, item in enumerate(records, start=1)
            )
        )
    else:
        parts.append(
            f"## 新增招标公告\n\n本期无新增招标公告。"
            f"以上覆盖范围内没有检索到发布日期晚于 {spec.window_start} 的 ESG 相关招标公告。"
        )
    return "\n\n".join(parts) + "\n", {"problems": [], "warnings": []}


def render(
    out_dir: Path, spec: CollectSpec, analysis: dict[str, Any], stats: dict[str, Any], charts: Sequence[str]
) -> dict[str, Any]:
    """写出 report.md；返回角标核对出的问题（problems 须改）与提醒（warnings）。"""
    data = read_json(out_dir / contract.DATA_FILE, {})
    search = search_summary(out_dir / WORK_DIR)
    if spec.case == "monthly-report":
        text, notes = _monthly(spec, data, analysis, stats, search)
    elif spec.mode == "summary":
        text, notes = _bid_summary(spec, data, analysis, stats, search, charts)
    else:
        text, notes = _daily(spec, data, analysis, search)
    (out_dir / contract.REPORT_FILE).write_text(text, encoding="utf-8")
    return notes
