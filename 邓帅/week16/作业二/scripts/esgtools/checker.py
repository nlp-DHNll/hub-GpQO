"""验收器：只读运行目录，判定这次运行是否合格。

只看运行目录里的产物，不区分产物由智能体还是脚本生成。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from esgtools.contract import (
    ARTIFACT_FILES,
    DATA_FILE,
    NOTICE_TYPE_NAMES,
    REPORT_FILE,
    RUN_RECORD_FILE,
    SEEN_SNAPSHOT_FILE,
    BidRecord,
    BidTable,
    EvidenceTable,
    NoticeType,
    RuleSet,
    Verification,
    as_dict,
    dedup_key,
    find_dates,
    load_bid_records,
    load_evidence,
    parse_date,
    raw_window,
    rule_set_of,
    validate_run_record,
)
from esgtools.reportparse import (
    Report,
    Section,
    declared_values,
    find_citations,
    find_off_spec_citations,
    find_urls,
    first_cell_ints,
    is_declared,
    split_sections,
    visible_chars,
)


@dataclass
class Check:
    """一条规则的判定结果。"""

    rule: str
    """规则标识，如 ``monthly.citations``。"""

    title: str
    """规则的中文名。"""

    passed: bool

    detail: str
    """通过时是概要，不通过时是逐条原因。"""


@dataclass
class Verdict:
    """一次运行目录的完整判定。"""

    run_dir: Path
    rule_set: RuleSet | None
    """规则集；运行记录读不出来时为 None。"""

    passed: bool
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """判定的 JSON 形态，供命令行 ``--json`` 与对比实验汇总使用。"""
        return {
            "run_dir": str(self.run_dir),
            "rule_set": self.rule_set.value if self.rule_set is not None else None,
            "passed": self.passed,
            "checks": [
                {
                    "rule": check.rule,
                    "title": check.title,
                    "passed": check.passed,
                    "detail": check.detail,
                }
                for check in self.checks
            ],
            "metrics": self.metrics,
        }


@dataclass
class _LoadedRun:
    """从运行目录读出的三件产物原文；读不出来的部分为 None。"""

    run_dir: Path
    report: str | None
    data: object
    record_raw: object
    problems: list[str]


@dataclass(frozen=True)
class SectionSpec:
    """报告里应有一节的规格：认标题的规则，以及是否必须带表格。"""

    name: str
    matches: Callable[[str], bool]
    needs_table: bool = False


def _section_problems(sections: list[Section], specs: list[SectionSpec], *, ordered: bool) -> list[str]:
    """按规格逐节检查有无、有无内容、有无表格；``ordered`` 时还检查先后。"""
    problems: list[str] = []
    found: list[tuple[SectionSpec, int]] = []
    for spec in specs:
        hits = [position for position, section in enumerate(sections) if spec.matches(section.title)]
        if not hits:
            problems.append(f"缺少『{spec.name}』一节")
            continue
        section = sections[hits[0]]
        if not section.content.strip():
            problems.append(f"『{spec.name}』一节只有标题、没有内容")
        elif spec.needs_table and not section.has_table():
            problems.append(f"『{spec.name}』下没有表格")
        found.append((spec, hits[0]))
    for (earlier, earlier_pos), (later, later_pos) in zip(found, found[1:], strict=False):
        if ordered and earlier_pos > later_pos:
            problems.append(f"章节顺序与规定不符：『{earlier.name}』应排在『{later.name}』之前")
    return problems


def read_json(path: Path) -> tuple[object, str | None]:
    """读一个 JSON 文件：返回 (解析结果, 读不了的原因)。原因以文件名开头，可直接拼进报告。"""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"{path.name} 不是合法的 JSON：{exc.msg}（第 {exc.lineno} 行）"
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{path.name} 无法读取：{exc}"


def _load_run(run_dir: Path) -> _LoadedRun:
    problems = [f"缺少 {name}" for name in ARTIFACT_FILES if not (run_dir / name).is_file()]
    report: str | None = None
    data: object = None
    record_raw: object = None
    if not problems:
        try:
            report = (run_dir / REPORT_FILE).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{REPORT_FILE} 无法读取：{exc}")
        else:
            if not report.strip():
                problems.append(f"{REPORT_FILE} 是空文件")
        data, problem = read_json(run_dir / DATA_FILE)
        if problem:
            problems.append(problem)
        record_raw, problem = read_json(run_dir / RUN_RECORD_FILE)
        if problem:
            problems.append(problem)
    return _LoadedRun(run_dir, report, data, record_raw, problems)


def check_run(run_dir: Path) -> Verdict:
    """判定一个运行目录。"""
    loaded = _load_run(run_dir)
    if loaded.problems:
        return Verdict(
            run_dir, None, False, [Check("artifacts", "三件产物齐全", False, "；".join(loaded.problems))]
        )

    record_problems = validate_run_record(loaded.record_raw)
    checks = [
        Check("artifacts", "三件产物齐全", True, f"{REPORT_FILE}、{DATA_FILE}、{RUN_RECORD_FILE} 均在"),
        Check(
            "run_record",
            "运行记录字段齐全",
            not record_problems,
            "；".join(record_problems) or "案例、版本、时间窗、模型、用量等字段均在",
        ),
    ]
    rule_set = rule_set_of(loaded.record_raw)
    metrics: dict[str, Any] = {"cost": _cost_metrics(loaded.record_raw)}
    if rule_set is not None:
        rule_checks, rule_metrics = _RULE_CHECKERS[rule_set](loaded)
        checks += rule_checks
        metrics.update(rule_metrics)
    passed = all(check.passed for check in checks)
    return Verdict(run_dir, rule_set, passed, checks, metrics)


def _cost_metrics(record_raw: object) -> dict[str, Any]:
    """成本与耗时，直接取自运行记录，供对比实验汇总。"""
    record = as_dict(record_raw)
    return {
        key: record.get(key)
        for key in ("duration_ms", "input_tokens", "output_tokens", "cost_usd", "search_count")
    }


# ---- 月报 ----

MONTHLY_SECTIONS: list[SectionSpec] = [
    SectionSpec("摘要与本月要点", lambda title: "摘要" in title and "要点" in title),
    SectionSpec("政策/评级/标准动态", lambda title: all(word in title for word in ("政策", "评级", "标准"))),
    SectionSpec("行业新闻与最佳实践", lambda title: "行业" in title and "最佳实践" in title),
    SectionSpec("客户公司动态的影响与建议", lambda title: "公司动态" in title and "建议" in title),
    SectionSpec("下月关注清单", lambda title: "关注" in title and "清单" in title),
    SectionSpec("方法与来源说明", lambda title: "方法" in title and "来源" in title),
    SectionSpec("证据表附录", lambda title: "证据表" in title),
]
"""月报的固定章节，按规格规定的先后排列。"""

MONTHLY_BENCHMARK_TABLE = SectionSpec(
    "对标企业关键行动对比表", lambda title: "对标" in title and "对比" in title, needs_table=True
)

MONTHLY_OPENING: list[tuple[str, str]] = [("客户", "text"), ("行业", "text"), ("时间窗", "dates")]
"""月报开头须写明的标签。"""


def _check_monthly(loaded: _LoadedRun) -> tuple[list[Check], dict[str, Any]]:
    report = split_sections(loaded.report or "")
    sections = report.sections
    evidence = load_evidence(loaded.data)
    section_problems = _section_problems(sections, MONTHLY_SECTIONS, ordered=True)
    section_problems += _section_problems(sections, [MONTHLY_BENCHMARK_TABLE], ordered=False)
    appendix = [section for section in sections if "证据表" in section.title]
    body = report.text_excluding(appendix)
    evidence_problems = list(evidence.problems)
    if not evidence.records and not evidence_problems:
        evidence_problems.append("证据表是空的：月报每条事实都要有角标对应的证据")
    checks = [
        Check(
            "monthly.evidence_fields",
            "证据表每条具备契约字段且取值合法",
            not evidence_problems,
            "；".join(evidence_problems) or f"{len(evidence.records)} 条证据字段均在",
        ),
        Check(
            "monthly.sections",
            "报告章节齐全且顺序正确",
            not section_problems,
            "；".join(section_problems) or "七个规定章节与对标企业对比表均在，顺序正确",
        ),
        _check_citations(body, appendix, evidence.ids),
        _check_opening(
            _opening_text(report, MONTHLY_SECTIONS),
            loaded.record_raw,
            rule="monthly.opening",
            title="报告开头声明客户、行业、时间窗",
            labels=MONTHLY_OPENING,
        ),
        _check_pending(sections),
    ]
    return checks, _monthly_metrics(evidence, body, loaded.record_raw)


def _opening_text(report: Report, required: Sequence[SectionSpec]) -> str:
    """第一个规定章节之前的全部文字；报告开头的声明写在这里。规定章节一个都没有时就是全文。"""
    first = next(
        (section for section in report.sections if any(spec.matches(section.title) for spec in required)),
        None,
    )
    return report.text_before(first) if first else "\n".join(report.lines)


def _check_citations(body: str, appendix: list[Section], evidence_ids: list[int]) -> Check:
    """正文角标、证据表（data.json）与证据表附录三处的角标编号须完全一致。``body`` 须不含附录。"""
    rule, title = "monthly.citations", "正文角标与证据表一一对应"
    if not appendix:
        return Check(rule, title, False, "报告里找不到『证据表附录』一节，无法核对角标")

    ids = [number for number in evidence_ids if number > 0]
    cited = find_citations(body)
    rows = first_cell_ints(appendix[0])
    problems: list[str] = ["正文没有任何角标，证据表也是空的"] if not ids and not cited else []
    if len(ids) != len(evidence_ids):
        problems.append(f"证据表里有 {len(evidence_ids) - len(ids)} 条没有可用的角标编号")
    if duplicated := sorted({number for number in ids if ids.count(number) > 1}):
        problems.append("证据表里角标编号重复：" + "、".join(str(number) for number in duplicated))
    if dangling := sorted(set(cited) - set(ids)):
        problems.append("正文角标在证据表里没有对应记录：" + "、".join(f"[{number}]" for number in dangling))
    if uncited := sorted(set(ids) - set(cited)):
        problems.append("证据表里有、正文没有引用：" + "、".join(f"第 {number} 条" for number in uncited))
    if missing_rows := sorted(set(ids) - set(rows)):
        problems.append("证据表附录里缺行：" + "、".join(f"角标 {number}" for number in missing_rows))
    if extra_rows := sorted(set(rows) - set(ids)):
        problems.append(
            "证据表附录多出证据表里没有的行：" + "、".join(f"角标 {number}" for number in extra_rows)
        )
    if off_spec := sorted(set(find_off_spec_citations(body))):
        hints = "、".join(f"{marker}（应写作 [{re.sub(r'\D', '', marker)}]）" for marker in off_spec)
        problems.append("角标须写成 [n]（n 为角标编号），正文里有非约定写法：" + hints)
    return Check(
        rule, title, not problems, "；".join(problems) or f"{len(cited)} 处角标与证据表 {len(ids)} 条一一对应"
    )


def _check_opening(
    opening: str, record_raw: object, *, rule: str, title: str, labels: Sequence[tuple[str, str]]
) -> Check:
    """报告开头的声明须写明每个标签。

    ``labels`` 是 (标签, 取值种类)：text 只要求有内容；dates 要求起止两个日期；
    count 要求数字；percent 要求百分数。写了时间窗的，还须与运行记录里的时间窗一致——
    对比实验靠运行记录证明两版跑的是同一时间窗。
    """
    declared = declared_values(opening)
    problems: list[str] = []
    window: list[date] = []
    for label, kind in labels:
        value = declared.get(label)
        if value is None or not is_declared(value):
            problems.append(f"报告开头的声明没有写明『{label}』")
        elif kind == "dates":
            dates = find_dates(value)
            if len(dates) < 2:
                problems.append(f"『{label}』里找不到起止两个日期：{value}")
            else:
                window = dates[:2]
        elif kind == "count" and not re.search(r"\d", value):
            problems.append(f"『{label}』里没有数字：{value}")
        elif kind == "percent" and not re.search(r"\d+(?:\.\d+)?\s*%", value):
            problems.append(f"『{label}』里没有百分数（应写成 80% 这样的形式）：{value}")
    if len(window) == 2:
        record_start, record_end = raw_window(record_raw)
        if record_start and record_end and (window[0], window[1]) != (record_start, record_end):
            problems.append(
                f"报告声明的时间窗（{window[0]} 至 {window[1]}）"
                f"与运行记录（{record_start} 至 {record_end}）不一致"
            )
    return Check(
        rule,
        title,
        not problems,
        "；".join(problems) or "报告开头已写明" + "、".join(label for label, _ in labels),
    )


def _check_pending(sections: list[Section]) -> Check:
    """待核实的线索须单独列成一节，不混进结论。"""
    rule, title = "monthly.pending", "待核实项单独列出"
    hits = [section for section in sections if "待核实" in section.title]
    if not hits:
        return Check(rule, title, False, "缺少『待核实事项』一节：待核实的线索须单列，不混进结论")
    if not hits[0].content.strip():
        return Check(
            rule, title, False, "『待核实事项』一节只有标题、没有内容；没有待核实项也要写明「本期无待核实项」"
        )
    return Check(rule, title, True, "待核实事项已单列")


def _monthly_metrics(evidence: EvidenceTable, body: str, record_raw: object) -> dict[str, Any]:
    """月报度量：合格来源数、日期落窗率、核实状态与可信度分级分布、角标数、正文字数。

    ``body`` 是不含证据表附录的正文。
    """
    start, end = raw_window(record_raw)
    used = [record for record in evidence.records if record.verification is not Verification.EXCLUDED]
    in_window = out_of_window = unknown = 0
    for record in used:
        published = parse_date(record.published_at)
        if published is None or start is None or end is None:
            unknown += 1
        elif start <= published <= end:
            in_window += 1
        else:
            out_of_window += 1
    return {
        "evidence_total": len(evidence.ids),
        "qualified_sources": sum(1 for record in used if record.credibility_tier <= 2),
        "verification_distribution": dict(Counter(record.verification.value for record in evidence.records)),
        "credibility_tier_distribution": {
            str(tier): count
            for tier, count in sorted(Counter(record.credibility_tier for record in evidence.records).items())
        },
        "date_in_window": {
            "in_window": in_window,
            "out_of_window": out_of_window,
            "unknown": unknown,
            "denominator": len(used),
            "rate": in_window / len(used) if used else None,
        },
        "citations": len(find_citations(body)),
        "body_chars": visible_chars(body),
    }


# ---- 汇总 ----

SUMMARY_SECTIONS: list[SectionSpec] = [
    SectionSpec("热点主题排行", lambda title: "主题" in title and ("热点" in title or "排行" in title)),
    SectionSpec("金额分布", lambda title: "金额" in title and "分布" in title),
    SectionSpec("月度趋势", lambda title: "趋势" in title and "月" in title),
    SectionSpec("采购人类型分布", lambda title: "采购人" in title and "类型" in title),
    SectionSpec("地区分布", lambda title: any(word in title for word in ("地区", "省份", "地域"))),
    SectionSpec("典型项目", lambda title: "典型" in title or "案例" in title),
]
"""汇总报告须有的分析项，不要求先后。"""

SUMMARY_APPENDIX = SectionSpec("边界外招标附录", lambda title: "边界外" in title)

SUMMARY_OPENING: list[tuple[str, str]] = [
    ("时间窗", "dates"),
    ("样本量", "count"),
    ("来源构成", "text"),
    ("金额可得率", "percent"),
]
"""汇总报告开头须写明的标签。"""


def _check_summary(loaded: _LoadedRun) -> tuple[list[Check], dict[str, Any]]:
    report = split_sections(loaded.report or "")
    sections = report.sections
    records = load_bid_records(loaded.data)
    section_problems = _section_problems(sections, SUMMARY_SECTIONS, ordered=False)
    record_problems = list(records.problems)
    if not records.records and not record_problems:
        record_problems.append("招标记录是空的：两年汇总要以样本为基础")
    checks = [
        Check(
            "summary.record_fields",
            "招标记录每条具备契约字段且取值合法",
            not record_problems,
            "；".join(record_problems) or f"{len(records.records)} 条招标记录字段均在",
        ),
        _check_opening(
            _opening_text(report, SUMMARY_SECTIONS),
            loaded.record_raw,
            rule="summary.opening",
            title="报告开头写明时间窗、样本量、来源构成、金额可得率",
            labels=SUMMARY_OPENING,
        ),
        Check(
            "summary.sections",
            "分析项齐全",
            not section_problems,
            "；".join(section_problems)
            or "热点主题排行、金额分布、月度趋势、采购人类型与地区分布、典型项目均在",
        ),
        _check_scope_appendix(report, records.records),
    ]
    return checks, _summary_metrics(records.records)


def _check_scope_appendix(report: Report, records: list[BidRecord]) -> Check:
    """边界外招标只进附录：附录以外的正文不能出现它们，附录也不能漏列。"""
    rule, title = "summary.appendix", "边界外招标只进附录"
    appendix = report.find(lambda heading: "边界外" in heading)
    if appendix is None:
        return Check(
            rule, title, False, "缺少『边界外招标』附录一节：与 ESG 沾边但不属于专业服务的招标只进附录"
        )
    out_of_scope = [record for record in records if not record.in_scope]
    body_keys = {dedup_key(url) for url in find_urls(report.text_excluding([appendix]))}
    appendix_keys = {dedup_key(url) for url in find_urls(appendix.content)}
    problems: list[str] = []
    if leaked := [record for record in out_of_scope if dedup_key(record.url) in body_keys]:
        problems.append("边界外招标出现在附录以外的正文里：" + "、".join(record.title for record in leaked))
    if unlisted := [record for record in out_of_scope if dedup_key(record.url) not in appendix_keys]:
        problems.append("附录漏列了边界外招标：" + "、".join(record.title for record in unlisted))
    if not problems and not appendix.content.strip():
        problems.append("『边界外招标』附录只有标题、没有内容；没有边界外招标也要写明原因")
    return Check(
        rule, title, not problems, "；".join(problems) or f"边界外招标 {len(out_of_scope)} 条均只在附录"
    )


def _summary_metrics(records: list[BidRecord]) -> dict[str, Any]:
    """汇总度量：样本量（范围内中标公告）、金额可得率、来源站点与主题构成。"""
    sample = [record for record in records if record.in_scope and record.notice_type is NoticeType.AWARD]
    with_amount = [record for record in sample if record.amount is not None]
    return {
        "records_total": len(records),
        "in_scope_total": sum(1 for record in records if record.in_scope),
        "out_of_scope_total": sum(1 for record in records if not record.in_scope),
        "sample_size": len(sample),
        "in_scope_tender_count": sum(
            1 for record in records if record.in_scope and record.notice_type is NoticeType.TENDER
        ),
        "amount_available": len(with_amount),
        "amount_rate": len(with_amount) / len(sample) if sample else None,
        "source_sites": dict(Counter(record.source_site or "未标注" for record in sample).most_common()),
        "topics": dict(Counter(record.topic or "未标注" for record in sample).most_common()),
    }


# ---- 日报（监控模式） ----

DAILY_OPENING: list[tuple[str, str]] = [("覆盖范围", "text")]
"""日报须注明的标签。"""

DAILY_EXTRA_FIELDS = ("deadline", "summary")
"""日报每条新增招标在招标记录十三个字段之外还须有的字段：截止日期（可得时）与一句话摘要。"""


def _check_daily(loaded: _LoadedRun) -> tuple[list[Check], dict[str, Any]]:
    report_text = loaded.report or ""
    records = load_bid_records(loaded.data)
    baseline, _ = raw_window(loaded.record_raw)
    seen = _load_seen(loaded.run_dir)
    seen_problems = list(seen.problems) + _seen_duplicates(records, seen.keys)
    field_problems = _daily_field_problems(records)
    notice_problems = _notice_type_problems(records)
    baseline_problems = _baseline_problems(records, baseline)
    listing_problems = _listing_problems(records, report_text)
    checks = [
        Check(
            "daily.record_fields",
            "日报每条新增招标具备契约字段、截止日期与一句话摘要",
            not field_problems,
            "；".join(field_problems) or f"{len(records.records)} 条新增招标字段均在",
        ),
        Check(
            "daily.notice_type",
            "日报只含招标公告",
            not notice_problems,
            "；".join(notice_problems) or "全部是招标公告",
        ),
        Check(
            "daily.baseline",
            "日报只含基线之后发布的招标公告",
            not baseline_problems,
            "；".join(baseline_problems) or f"全部晚于基线 {baseline}",
        ),
        Check(
            "daily.seen",
            "日报条目与已见清单无交集",
            not seen_problems,
            "；".join(seen_problems) or f"与运行前的已见清单（{len(seen.keys)} 条）没有重复",
        ),
        _check_opening(
            report_text,
            loaded.record_raw,
            rule="daily.coverage",
            title="日报已注明覆盖范围",
            labels=DAILY_OPENING,
        ),
        Check(
            "daily.listing",
            "日报正文列出每条新增招标",
            not listing_problems,
            "；".join(listing_problems) or f"{len(records.records)} 条新增招标均在正文中列出",
        ),
    ]
    return checks, _daily_metrics(records, baseline, len(seen.keys))


def _daily_field_problems(records: BidTable) -> list[str]:
    """十三个契约字段之外，日报条目还须有截止日期与一句话摘要；采购人与摘要不能是空串。"""
    problems = list(records.problems)
    for index, raw in enumerate(records.raws, start=1):
        if missing := [name for name in DAILY_EXTRA_FIELDS if name not in raw]:
            problems.append(f"第 {index} 条 缺少字段：" + "、".join(missing))
    for index, record in enumerate(records.entries, start=1):
        if record is None:
            continue
        for name, label in (("purchaser", "采购人"), ("summary", "一句话摘要")):
            value = getattr(record, name)
            if value is not None and not value.strip():
                problems.append(f"第 {index} 条 {name}：日报条目须写明{label}（取不到写 null）")
    return problems


def _notice_type_problems(records: BidTable) -> list[str]:
    """监控只提醒「将要采购」，中标公告与其它公告都不该出现在日报里。"""
    return [
        f"第 {index} 条的公告类型是{NOTICE_TYPE_NAMES[record.notice_type]}，日报只收招标公告：{record.title}"
        for index, record in enumerate(records.entries, start=1)
        if record is not None and record.notice_type is not NoticeType.TENDER
    ]


def _baseline_problems(records: BidTable, baseline: date | None) -> list[str]:
    """日报条目的发布日期须能解析，且严格晚于基线日；基线日当天的也不算新增。"""
    problems: list[str] = []
    for index, record in enumerate(records.entries, start=1):
        if record is None:
            continue
        published = parse_date(record.published_at)
        if published is None:
            problems.append(f"第 {index} 条发布日期无法解析：{record.published_at!r}")
        elif baseline is None:
            problems.append("运行记录里读不出基线日期，无法判定是否为新增")
        elif published <= baseline:
            problems.append(f"第 {index} 条的发布日期 {published} 不晚于基线 {baseline}：{record.title}")
    return problems


@dataclass
class _Seen:
    """运行前的已见清单快照。"""

    keys: set[str]
    """快照里每条招标的去重键。"""

    problems: list[str]
    """快照自身的问题：缺失、读不出来、有条目没有地址。"""


def _seen_duplicates(records: BidTable, seen_keys: set[str]) -> list[str]:
    """日报条目里有哪些已在已见清单中——它们运行前就推送过，不该再出现。"""
    return [
        f"第 {index} 条已在已见清单里（运行前就推送过）：{record.title}"
        for index, record in enumerate(records.entries, start=1)
        if record is not None and dedup_key(record.url) in seen_keys
    ]


def _load_seen(run_dir: Path) -> _Seen:
    snapshot = run_dir / SEEN_SNAPSHOT_FILE
    if not snapshot.is_file():
        return _Seen(
            set(), [f"缺少已见清单快照 {SEEN_SNAPSHOT_FILE}，无法证明日报条目不在已见清单里（去重无据）"]
        )
    raw, problem = read_json(snapshot)
    if problem is not None:
        return _Seen(set(), [problem])
    items = raw if isinstance(raw, list) else as_dict(raw).get("records")
    if not isinstance(items, list):
        return _Seen(set(), [f"{SEEN_SNAPSHOT_FILE} 须是招标记录数组，或含 records 数组的对象"])

    keys: set[str] = set()
    without_url = 0
    for item in items:
        url = as_dict(item).get("url")
        if isinstance(url, str):
            keys.add(dedup_key(url))
        else:
            without_url += 1
    problems = [f"已见清单快照里有 {without_url} 条没有 url"] if without_url else []
    return _Seen(keys, problems)


def _listing_problems(records: BidTable, report_text: str) -> list[str]:
    """每条新增招标的链接都要出现在日报正文里；没有新增时，日报也要写明「无新增」。"""
    listed = {dedup_key(url) for url in find_urls(report_text)}
    problems = [
        f"日报正文里没有列出第 {index} 条：{record.title}"
        for index, record in enumerate(records.entries, start=1)
        if record is not None and dedup_key(record.url) not in listed
    ]
    if not records.records and "无新增" not in report_text:
        problems.append("没有新增招标时，日报也要写明「无新增」")
    return problems


def _daily_metrics(records: BidTable, baseline: date | None, seen_count: int) -> dict[str, Any]:
    """日报度量：新增条数、已见清单条数、基线与最晚发布日期。"""
    published = [found for record in records.records if (found := parse_date(record.published_at))]
    return {
        "record_count": len(records.records),
        "seen_before_count": seen_count,
        "baseline": baseline.isoformat() if baseline else None,
        "latest_published_at": max(published).isoformat() if published else None,
    }


_RULE_CHECKERS: dict[RuleSet, Callable[[_LoadedRun], tuple[list[Check], dict[str, Any]]]] = {
    RuleSet.MONTHLY: _check_monthly,
    RuleSet.SUMMARY: _check_summary,
    RuleSet.DAILY: _check_daily,
}
