"""运行产物契约：运行目录里放什么文件、每个字段叫什么、取哪些值。

规格「运行产物契约」一节是唯一依据；验收器与无头运行器都只认这里定义的名字。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any
from urllib.parse import parse_qsl, urlencode, urlparse

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

REPORT_FILE = "report.md"
"""报告正文（Markdown）。"""

DATA_FILE = "data.json"
"""结构化数据：月报为证据表，招投标为招标记录。"""

RUN_RECORD_FILE = "run.json"
"""运行记录。"""

ARTIFACT_FILES = (REPORT_FILE, DATA_FILE, RUN_RECORD_FILE)
"""每次运行必须留下的三件产物。"""

SEEN_SNAPSHOT_FILE = "seen_before.json"
"""监控模式额外留下的第四件产物：运行前已见清单的快照，验收器据此判定日报条目不在其中。"""


# ---- 取值 ----


class Case(StrEnum):
    """案例：两个 skill 各对应一个案例。"""

    MONTHLY_REPORT = "monthly-report"
    BID_RADAR = "bid-radar"


class Mode(StrEnum):
    """运行模式：月报只有一种；招投标情报分汇总与监控。"""

    REPORT = "report"
    SUMMARY = "summary"
    MONITOR = "monitor"


class Version(StrEnum):
    """版本：无脚本版 / 脚本版。"""

    NOSCRIPT = "noscript"
    SCRIPTED = "scripted"


class Invocation(StrEnum):
    """运行方式：无头（子会话）/ 交互。"""

    HEADLESS = "headless"
    INTERACTIVE = "interactive"
    SCRIPT = "script"
    """脚本版不经智能体、直接在命令行跑完整个流水线。"""


class RuleSet(StrEnum):
    """验收器的三套规则。"""

    MONTHLY = "monthly"
    SUMMARY = "summary"
    DAILY = "daily"


_RULE_SETS: dict[tuple[Case, Mode], RuleSet] = {
    (Case.MONTHLY_REPORT, Mode.REPORT): RuleSet.MONTHLY,
    (Case.BID_RADAR, Mode.SUMMARY): RuleSet.SUMMARY,
    (Case.BID_RADAR, Mode.MONITOR): RuleSet.DAILY,
}


def _as_enum[E: StrEnum](enum_type: type[E], value: object) -> E | None:
    """把 JSON 里的取值认成枚举；不是字符串或不在约定取值内都返回 None。"""
    if not isinstance(value, str):
        return None
    try:
        return enum_type(value)
    except ValueError:
        return None


def rule_set_for(case: Case, mode: Mode) -> RuleSet | None:
    """案例 × 运行模式对应的规则集；对不上的组合（如月报配监控）返回 None。"""
    return _RULE_SETS.get((case, mode))


def mode_mismatch_message(case: Case, mode: Mode) -> str:
    """案例与运行模式对不上的原因；对得上返回空串。运行记录校验与运行器共用这一处。"""
    if rule_set_for(case, mode) is not None:
        return ""
    if case is Case.MONTHLY_REPORT:
        return "月报的运行模式 mode 须为 report"
    return "招投标情报的运行模式 mode 须为 summary（汇总）或 monitor（监控）"


def rule_set_of(record_raw: object) -> RuleSet | None:
    """从运行记录原文认出案例与运行模式，决定用哪套规则；认不出返回 None。"""
    if not isinstance(record_raw, dict):
        return None
    case = _as_enum(Case, record_raw.get("case"))
    mode = _as_enum(Mode, record_raw.get("mode"))
    if case is None or mode is None:
        return None
    return rule_set_for(case, mode)


# ---- 日期 ----

_DATE_PATTERN = re.compile(r"(\d{4})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})")
"""数字写法：2026-11-25、2026/11/25、2026年11月25日；带时分的取日期部分。"""

_ENGLISH_MONTH_FIRST = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})\b")
"""英文写法，月在前：Nov 24, 2026、November 24 2026。"""

_ENGLISH_DAY_FIRST = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s*,?\s*(\d{4})\b")
"""英文写法，日在前：24 November 2026。"""

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
"""英文月份名的前三个字母 → 月数；英文名只认这几个，其余词不当月份。"""


def _month_number(name: str) -> int | None:
    return _MONTHS.get(name[:3].lower())


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _all_dates(text: str) -> list[date]:
    """一段文字里能认出的全部日期，按在文字里出现的位置排序。"""
    hits: list[tuple[int, date]] = []
    for matched in _DATE_PATTERN.finditer(text):
        if found := _safe_date(int(matched[1]), int(matched[2]), int(matched[3])):
            hits.append((matched.start(), found))
    for matched in _ENGLISH_MONTH_FIRST.finditer(text):
        month = _month_number(matched[1])
        if month is not None and (found := _safe_date(int(matched[3]), month, int(matched[2]))):
            hits.append((matched.start(), found))
    for matched in _ENGLISH_DAY_FIRST.finditer(text):
        month = _month_number(matched[2])
        if month is not None and (found := _safe_date(int(matched[3]), month, int(matched[1]))):
            hits.append((matched.start(), found))
    return [found for _, found in sorted(hits, key=lambda hit: hit[0])]


def parse_date(value: object) -> date | None:
    """把日期的常见写法解析成日期；认不出返回 None。

    认这些写法：2026-11-25、2026/11/25、2026年11月25日（带时分的取日期部分），
    以及英文的 Nov 24, 2026、24 November 2026——英文来源的发布日期常是这种写法。
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    return next(iter(_all_dates(value)), None)


def find_dates(text: object) -> list[date]:
    """一段文字里按出现顺序能认出的全部日期。"""
    return _all_dates(text) if isinstance(text, str) else []


def raw_window(record_raw: object) -> tuple[date | None, date | None]:
    """从运行记录原文取时间窗的起止日期；记录整体不合规时也尽量取，供度量与核对使用。"""
    window = as_dict(as_dict(record_raw).get("time_window"))
    return parse_date(window.get("start")), parse_date(window.get("end"))


def _to_date(value: object) -> date:
    """字段校验用：解析不了就抛错，由字段校验报给使用者。"""
    parsed = parse_date(value)
    if parsed is None:
        raise ValueError(f"日期无法解析：{value!r}（可写 2026-11-25、2026/11/25、2026年11月25日）")
    return parsed


DateValue = Annotated[date, BeforeValidator(_to_date)]


# ---- 运行记录 ----


class TimeWindow(BaseModel):
    """时间窗：起止日期。监控模式下 start 即基线日。"""

    model_config = ConfigDict(extra="allow")

    start: DateValue
    end: DateValue

    @model_validator(mode="after")
    def _start_not_after_end(self) -> TimeWindow:
        if self.start > self.end:
            raise ValueError("起始日期晚于结束日期")
        return self


class RunRecord(BaseModel):
    """运行记录：一次运行的元数据。用量字段允许为 null，表示这一项没取到。"""

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    run_id: str = Field(min_length=1)
    case: Case
    mode: Mode
    version: Version
    skill_version: str = Field(min_length=1)
    client: str | None
    industry: str | None
    time_window: TimeWindow
    model: str = Field(min_length=1)
    started_at: str = Field(min_length=1)
    duration_ms: Annotated[int, Field(ge=0)] | None
    input_tokens: Annotated[int, Field(ge=0)] | None
    output_tokens: Annotated[int, Field(ge=0)] | None
    cost_usd: Annotated[float, Field(ge=0)] | None
    search_count: Annotated[int, Field(ge=0)] | None
    invocation: Invocation

    @model_validator(mode="after")
    def _mode_matches_case(self) -> RunRecord:
        if message := mode_mismatch_message(self.case, self.mode):
            raise ValueError(message)
        return self


# ---- 证据表（月报的结构化数据） ----


class Verification(StrEnum):
    """核实状态。"""

    VERIFIED = "verified"
    """已核实：打开过原文并核对。"""

    SUMMARY_ONLY = "summary-only"
    """仅见摘要。"""

    EXCLUDED = "excluded"
    """已排除。"""


VERIFICATION_NAMES: dict[Verification, str] = {
    Verification.VERIFIED: "已核实",
    Verification.SUMMARY_ONLY: "仅见摘要",
    Verification.EXCLUDED: "已排除",
}
"""核实状态的中文叫法（规格原文用词）；显示与别名归一都以它为准。"""

_VERIFICATION_ALIASES = {name: member.value for member, name in VERIFICATION_NAMES.items()} | {
    "summary_only": "summary-only"
}

TIER_NAMES: dict[int, str] = {1: "一级", 2: "二级", 3: "三级"}
"""可信度分级的中文叫法。"""

_TIER_ALIASES = {name: tier for tier, name in TIER_NAMES.items()} | {"1": 1, "2": 2, "3": 3}
_URL_PATTERN = re.compile(r"^https?://[^\s/:?#]+(?:[/?#]\S*)?$")
QUOTE_MAX_CHARS = 50
"""原文摘录的字数上限。"""


def _verification(value: object) -> object:
    """规格里的中文叫法（已核实 / 仅见摘要 / 已排除）归一成约定取值。"""
    if isinstance(value, str):
        return _VERIFICATION_ALIASES.get(value.strip(), value)
    return value


def _tier(value: object) -> object:
    """可信度分级接受 1/2/3、"1"/"2"/"3" 与 一级/二级/三级。"""
    if isinstance(value, str):
        return _TIER_ALIASES.get(value.strip(), value)
    return value


def _web_url(value: object) -> object:
    if isinstance(value, str) and not _URL_PATTERN.match(value.strip()):
        raise ValueError("须是 http:// 或 https:// 开头的网页地址")
    return value


def _quote(value: object) -> object:
    if isinstance(value, str) and len(value.strip()) > QUOTE_MAX_CHARS:
        raise ValueError(f"原文摘录超过 {QUOTE_MAX_CHARS} 字（实际 {len(value.strip())} 字）")
    return value


def _positive_int(value: object) -> object:
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return value


class EvidenceRecord(BaseModel):
    """证据表的一条：支撑正文中一个角标。"""

    model_config = ConfigDict(extra="allow")

    id: Annotated[int, Field(ge=1), BeforeValidator(_positive_int)]
    """角标编号。"""

    section: str = Field(min_length=1)
    """所属章节。"""

    claim: str = Field(min_length=1)
    """支撑的结论。"""

    url: Annotated[str, BeforeValidator(_web_url)]
    """来源地址。"""

    published_at: str | None
    """发布日期，保留找到时的写法；确实取不到写 null。"""

    quote: Annotated[str, BeforeValidator(_quote)]
    """不超过 50 字的原文摘录。"""

    credibility_tier: Annotated[int, Field(ge=1, le=3), BeforeValidator(_tier)]
    """可信度分级：一级、二级为可用来源，三级只作线索。"""

    verification: Annotated[Verification, BeforeValidator(_verification)]
    """核实状态。"""

    @model_validator(mode="after")
    def _quote_unless_excluded(self) -> EvidenceRecord:
        if not self.quote.strip() and self.verification is not Verification.EXCLUDED:
            raise ValueError("quote：未排除的证据须有原文摘录")
        return self


@dataclass
class EvidenceTable:
    """读出来的证据表。"""

    records: list[EvidenceRecord]
    """读得出来、字段合规的证据。"""

    ids: list[int]
    """每条记录的角标编号，含字段不合规的记录——核对角标对应关系时不该漏掉它们。"""

    problems: list[str]
    """不合规之处；空列表表示整张证据表合规。"""


def _read_records[R: BaseModel](
    data_raw: object, key: str, what: str, model: type[R]
) -> tuple[list[R | None], list[dict[str, Any]], list[str]]:
    """读出结构化数据 ``key`` 下的记录数组。

    返回 (逐条对应的记录, 每条记录的原文, 不合规之处)；字段不合规的记录在第一项里记 None，
    这样报错与核对都能用「第几条」指回原文。
    """
    items = as_dict(data_raw).get(key)
    if not isinstance(items, list):
        return [], [], [f"data.json 顶层须是对象，且含 {key}（{what}）数组"]
    records: list[R | None] = []
    raws: list[dict[str, Any]] = []
    problems: list[str] = []
    for index, item in enumerate(items):
        raws.append(as_dict(item))
        try:
            records.append(model.model_validate(item))
        except ValidationError as exc:
            records.append(None)
            problems.extend(f"第 {index + 1} 条 {text}" for text in _format_errors(exc))
    return records, raws, problems


def load_evidence(data_raw: object) -> EvidenceTable:
    """读出证据表。"""
    entries, raws, problems = _read_records(data_raw, "evidence", "证据表", EvidenceRecord)
    records = [record for record in entries if record is not None]
    return EvidenceTable(records, [_loose_int(raw.get("id")) for raw in raws], problems)


def as_dict(value: object) -> dict[str, Any]:
    """是对象就返回它，否则返回空对象，方便对来历不明的 JSON 取字段。"""
    return value if isinstance(value, dict) else {}


def _loose_int(value: object) -> int:
    """尽量把编号读成整数；读不出记 0，表示「没有可用编号」。"""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return 0


# ---- 校验与报错 ----

# pydantic 的报错是英文，这里换成中文并带上上下限；自定义校验函数抛出的消息本身就是中文，原样保留。
_ERROR_HINTS: dict[str, str] = {
    "missing": "缺少字段",
    "int_parsing": "须为整数",
    "int_type": "须为整数",
    "float_parsing": "须为数字",
    "float_type": "须为数字",
    "string_type": "须为字符串",
    "string_too_short": "不能为空",
    "string_too_long": "不能多于 {max_length} 字",
    "model_type": "须为对象",
    "greater_equal": "不能小于 {ge}",
    "less_equal": "不能大于 {le}",
    "date_type": "日期无法解析",
}


def _format_errors(exc: ValidationError) -> list[str]:
    """把一份校验错误整理成「字段：原因」的中文条目。"""
    items: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        kind = str(err["type"])
        if kind == "enum":
            expected = str(err.get("ctx", {}).get("expected", ""))
            reason = f"取值不在约定范围（{expected}）" if expected else "取值不在约定范围"
        elif kind == "value_error":
            reason = str(err["msg"]).removeprefix("Value error, ")
        else:
            hint = _ERROR_HINTS.get(kind)
            try:
                reason = hint.format_map(defaultdict(str, err.get("ctx") or {})) if hint else str(err["msg"])
            except (KeyError, IndexError, ValueError):
                reason = str(err["msg"])
        items.append(f"{loc}：{reason}" if loc else reason)
    return items


def validate_run_record(record_raw: object) -> list[str]:
    """校验运行记录；返回不合规之处的列表，空列表表示合规。月报还须写明客户与行业。"""
    try:
        record = RunRecord.model_validate(record_raw)
    except ValidationError as exc:
        return _format_errors(exc)
    problems: list[str] = []
    if record.case is Case.MONTHLY_REPORT:
        for name, label in (("client", "客户"), ("industry", "行业")):
            if not (getattr(record, name) or "").strip():
                problems.append(f"{name}：月报的运行记录须写明{label}")
    return problems


# ---- 招标记录（招投标情报的结构化数据） ----


class NoticeType(StrEnum):
    """公告类型。"""

    TENDER = "tender"
    """招标公告：将要采购，监控模式只关心它。"""

    AWARD = "award"
    """中标公告：已采购，两年汇总的统计对象。"""

    OTHER = "other"
    """其它：更正、答疑、废标等。"""


NOTICE_TYPE_NAMES: dict[NoticeType, str] = {
    NoticeType.TENDER: "招标公告",
    NoticeType.AWARD: "中标公告",
    NoticeType.OTHER: "其它",
}
"""公告类型的中文叫法（规格原文用词）；显示与别名归一都以它为准。"""

_NOTICE_TYPE_ALIASES = {name: member.value for member, name in NOTICE_TYPE_NAMES.items()} | {"其他": "other"}


def _notice_type(value: object) -> object:
    """规格里的中文叫法（招标公告 / 中标公告 / 其它）归一成约定取值。"""
    if isinstance(value, str):
        return _NOTICE_TYPE_ALIASES.get(value.strip(), value)
    return value


class BidRecord(BaseModel):
    """招标记录的一条。规格列出的十三个字段一个都不能少；取不到的写 null。"""

    model_config = ConfigDict(extra="allow")

    title: str = Field(min_length=1)
    """标题。"""

    url: Annotated[str, BeforeValidator(_web_url)]
    """来源地址。"""

    notice_type: Annotated[NoticeType, BeforeValidator(_notice_type)]
    """公告类型。"""

    published_at: str | None
    """发布日期，保留找到时的写法；确实取不到写 null。"""

    purchaser: str | None
    """采购人。"""

    region: str | None
    """地区。"""

    topic: str | None
    """主题标签。"""

    in_scope: bool
    """是否在范围内（ESG/双碳专业服务）。"""

    amount: Annotated[float, Field(ge=0)] | None
    """中标金额，换算成元的数值。"""

    amount_text: str | None
    """中标金额在原文里的写法，如「190万元」。"""

    winner: str | None
    """中标人，可得时才有。"""

    source_site: str | None
    """来源站点。"""

    verification: Annotated[Verification, BeforeValidator(_verification)]
    """核实状态。"""

    deadline: str | None = None
    """截止日期，保留原文写法。日报的每条新增招标必须有这个字段，取不到写 null。"""

    summary: str | None = None
    """一句话摘要。日报的每条新增招标必须有这个字段。"""


@dataclass
class BidTable:
    """读出来的招标记录。"""

    entries: list[BidRecord | None]
    """与 data.json 逐条对应；字段不合规的记 None。"""

    raws: list[dict[str, Any]]
    """每条记录的原文。"""

    problems: list[str]
    """不合规之处；空列表表示全部合规。"""

    @property
    def records(self) -> list[BidRecord]:
        """读得出来、字段合规的记录。"""
        return [record for record in self.entries if record is not None]


def load_bid_records(data_raw: object) -> BidTable:
    """读出招标记录。"""
    entries, raws, problems = _read_records(data_raw, "records", "招标记录", BidRecord)
    return BidTable(entries, raws, problems)


# ---- 去重键 ----

_TRACKING_PREFIXES = ("utm_", "share_")
_TRACKING_NAMES = {
    "from",
    "spm",
    "spm_id_from",
    "src",
    "ref",
    "refer",
    "reference",
    "source",
    "search_source",
    "share_from",
    "vd_source",
    "sessionid",
    "qid",
}


def dedup_key(url: str) -> str:
    """招标记录的去重键：同一个公告页面的不同写法得到同一个键。

    不影响身份的差别：http 与 https、主机大小写与默认端口、末尾斜杠、# 片段、
    跟踪参数（utm_*、from、spm、share_* 等）；其余查询参数按参数名排序后保留。
    """
    text = url.strip()
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return text
    host = parsed.netloc.lower().removesuffix(":80").removesuffix(":443")
    path = parsed.path.rstrip("/")
    params = sorted(
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_param(name)
    )
    query = "?" + urlencode(params) if params else ""
    return f"{host}{path}{query}"


def _is_tracking_param(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith(_TRACKING_PREFIXES) or lowered in _TRACKING_NAMES
