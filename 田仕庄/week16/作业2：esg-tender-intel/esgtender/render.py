"""统计聚合 + Jinja2 渲染。

统计全部在这里算完再交给模板——模板里不做计算，避免「页面上的数字
和 records.json 对不上」这类最难查的 bug。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .extract import STAGE_LABELS  # 阶段 code → 展示名，统计与渲染共用一份

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "templates"


@dataclass(slots=True)
class ReportContext:
    """模板上下文的唯一契约。

    之前是「调用方拼 dict + render 里再补一份默认值清单」，模板加字段时两处
    都要改、漏一处就在某条路径上炸 ``UndefinedError``。现在字段只在这里声明，
    缺省值随字段走，``render_report`` 也不再猜哪些键可能不存在。
    """

    meta: dict[str, Any]
    records: list[dict[str, Any]]
    stats: dict[str, Any]
    coverage: dict[str, str]
    trend: list[dict[str, Any]] = field(default_factory=list)
    suspects: list[dict[str, Any]] = field(default_factory=list)
    stages: list[dict[str, Any]] = field(default_factory=list)
    incremental: dict[str, Any] | None = None
    preset: dict[str, Any] | None = None
    report_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def coerce(cls, context: "ReportContext | dict[str, Any]") -> "ReportContext":
        if isinstance(context, cls):
            return context
        return cls(
            meta=dict(context.get("meta") or {}),
            records=list(context.get("records") or []),
            stats=dict(context.get("stats") or {}),
            coverage=dict(context.get("coverage") or {}),
            trend=list(context.get("trend") or []),
            suspects=list(context.get("suspects") or []),
            stages=list(context.get("stages") or []),
            incremental=context.get("incremental"),
            preset=context.get("preset"),
            report_path=str(context.get("report_path") or ""),
        )

# 一种格式一个模板，模板里不写死文件名。docx 不是模板渲染出来的（它是 OOXML
# 二进制包），由 docx_export 直接生成，但对外仍按「格式」统一暴露。
TEMPLATES = {"html": "tender_list.html.j2", "md": "tender_list.md.j2"}
FILENAMES = {
    "html": "tender_list.html",
    "md": "tender_list.md",
    "docx": "tender_list.docx",
}
FORMATS = ("html", "md", "docx")

DEFAULT_FORMAT = "html"
DEFAULT_TEMPLATE = TEMPLATES[DEFAULT_FORMAT]

GROUP_LABEL = {"core": "核心", "extended": "扩展", "edge": "边缘", "none": "未命中"}
GROUP_ORDER = {"core": 0, "extended": 1, "edge": 2, "none": 3}
# 阶段展示顺序（招标 → 中标成交 → 变更 → 其他），用 **code** 而不是中文标签表达。
# 标签只是展示层的东西，取值以 extract.STAGE_LABELS 为准：曾在这里复制一份
# 中文清单、统计又按字面量 `stage_counter.get("招标")` 读回，结果改一个字
# KPI 就静默变成 0，页面显示「可投 0 条」而记录里明明有招标公告。
STAGE_ORDER = ["tender", "award", "change", "other"]


def track_label(group: str, track_id: str) -> str:
    if group == "edge":
        return "边缘-关联"
    return f"{GROUP_LABEL.get(group, group)}-{track_id}"


def build_coverage(meta: dict[str, Any]) -> dict[str, str]:
    """把列表拼成字符串。模板里做拼接会被 trim_blocks 吃掉换行，把项目符号连成一行。"""
    queries = "、".join(f"「{q}」" for q in meta.get("queries") or []) or "无"
    failures = meta.get("failures") or []
    if failures:
        failure_text = "；".join(
            f"「{item['query']}」（{item['reason']}）" for item in failures
        )
    else:
        failure_text = "无，本轮全部 query 均返回结果"
    provider = str(meta.get("provider") or "")
    # 不带 Markdown 强调符号：同一份数据要喂给 HTML 与 Markdown 两套模板
    provider_text = (
        f"{provider}（离线样本，非真实数据，仅用于验证流程）"
        if provider == "fixture"
        else provider
    )
    sources = meta.get("sources") or {}
    used = sources.get("used") or []
    if used:
        provider_text += "；定向源 " + "、".join(
            f"{item.get('name')}（{item.get('mode')}，{item.get('hits', 0)} 条）" for item in used
        )
    else:
        provider_text += "；未启用定向源（加 --sources 可按 config/sources.yaml 追加）"
    preset = meta.get("preset") or {}
    if preset.get("title"):
        provider_text += f"；行业预设 {preset['title']}"
    return {"queries": queries, "failures": failure_text, "provider": provider_text}


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def fmt_amount(value: Any) -> str:
    """1200000 → 「120.00 万元」。None → N/A。"""
    amount = _to_decimal(value)
    if amount is None:
        return "N/A"
    if amount >= Decimal(10**8):
        return f"{amount / Decimal(10**8):.2f} 亿元"
    if amount >= Decimal(10**4):
        return f"{amount / Decimal(10**4):.2f} 万元"
    return f"{amount:.2f} 元"


def fmt_amount_wan(value: Any) -> str:
    """固定用「万元」输出，供趋势列使用。

    自动换单位在表格列里是灾难：一列同时出现「3.16 亿元」和「6286.42 万元」，
    读者没法比较大小，还得自己换算。
    """
    amount = _to_decimal(value)
    if amount is None:
        return "N/A"
    return f"{amount / Decimal(10**4):,.2f} 万元"


def thousands(value: Any) -> str:
    """16204 → 「16,204」。数不清位数的漏斗数字读起来太费劲。"""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def cell(text: Any) -> str:
    """转义 Markdown 表格里的竖线与换行。"""
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def build_stats(records: list[dict], buckets: list[dict]) -> dict[str, Any]:
    group_counter: Counter[str] = Counter()
    track_counter: Counter[tuple[str, str, str]] = Counter()
    bucket_counter: Counter[str] = Counter()
    stage_counter: Counter[str] = Counter()
    amounts: list[Decimal] = []
    award_amounts: list[Decimal] = []

    for record in records:
        track = record.get("track") or {}
        group = track.get("group", "none")
        group_counter[group] += 1
        # 带上赛道中文名：只显示「核心-T1」读者看不懂，显示「核心·ESG 报告编制与鉴证」才行
        track_counter[(group, track.get("id", ""), track.get("name", ""))] += 1
        bucket_counter[record.get("amount_bucket") or "N/A"] += 1
        amount = _to_decimal((record.get("fields") or {}).get("amount_cny"))
        if amount is not None:
            amounts.append(amount)
        stage = record.get("stage") or {}
        code = stage.get("code")
        if code:
            stage_counter[code] += 1  # key 用 code，展示名在下面统一映射
            if code == "award" and amount is not None:
                award_amounts.append(amount)

    # 阶段按固定顺序输出（招标 → 中标成交 → 变更 → 其他），不按数量排序：
    # 「可投的有几条」比「哪一类最多」更重要，顺序不能随数据抖动。
    ordered_codes = [code for code in STAGE_ORDER if code in stage_counter]
    ordered_codes.extend(
        code for code in stage_counter if code not in ordered_codes
    )
    by_stage = [
        {"code": code, "label": STAGE_LABELS.get(code, code), "count": stage_counter[code]}
        for code in ordered_codes
    ]
    tender_count = stage_counter.get("tender", 0)
    award_count = stage_counter.get("award", 0)

    # 按 scope 定义的顺序输出金额档，未出现的补 0，避免图表前后不一致
    ordered_buckets = [
        {"label": str(b["label"]), "count": bucket_counter.get(str(b["label"]), 0)}
        for b in buckets
    ]
    ordered_buckets.append({"label": "N/A", "count": bucket_counter.get("N/A", 0)})

    # 赛道按「核心 → 扩展 → 边缘」再按编号排序，不按数量排序——数量会随数据变，
    # 顺序跳来跳去读者每次都要重新找位置。
    ordered_tracks = sorted(
        track_counter.items(),
        key=lambda item: (GROUP_ORDER.get(item[0][0], 9), item[0][1]),
    )

    by_track = [
        {
            "label": f"{GROUP_LABEL.get(g, g)}·{name}" if name else track_label(g, t),
            # key 供 HTML 的下拉筛选与记录行对齐；label 只负责展示
            "key": name or track_label(g, t),
            "group": g,
            "count": c,
        }
        for (g, t, name), c in ordered_tracks
    ]

    return {
        "total": len(records),
        "by_group": [
            {"label": GROUP_LABEL.get(g, g), "count": c}
            for g, c in sorted(group_counter.items(), key=lambda kv: GROUP_ORDER.get(kv[0], 9))
        ],
        # pct 是条形图宽度（相对同组最大值），在 Python 里算完，模板不做算术
        "by_track": with_pct(by_track),
        # N/A 通常占绝对多数（预算写在正文表格，摘要里没有），把它算进峰值会把
        # 真实分档压成一条线，所以计算宽度时排除它，页面上单独说明条数
        "by_bucket": with_pct(ordered_buckets, skip={"N/A"}),
        "by_stage": with_pct(by_stage),
        "tender_count": tender_count,
        "award_count": award_count,
        "award_sum": fmt_amount(sum(award_amounts)) if award_amounts else "N/A",
        "award_amount_known": len(award_amounts),
        "new_count": sum(1 for r in records if (r.get("flags") or {}).get("is_new")),
        "amount_unknown": bucket_counter.get("N/A", 0),
        "amount_known": len(amounts),
        "amount_sum": fmt_amount(sum(amounts)) if amounts else "N/A",
        "amount_median": fmt_amount(median(amounts)) if amounts else "N/A",
        "needs_review": sum(1 for r in records if (r.get("flags") or {}).get("needs_review")),
        "suspects": sum(1 for r in records if (r.get("flags") or {}).get("suspect_of")),
    }


def with_pct(
    rows: list[dict[str, Any]], skip: set[str] | None = None
) -> list[dict[str, Any]]:
    """给每行补 ``pct``（0–100，相对本组最大值）与 ``share``（0–100，占本组合计）。

    ``pct`` 是 HTML 条形图的宽度：用「占最大值的比例」而不是「占总数」，
    因为占总数时长尾会被压成 1 像素，看不出差异。但它**不是占比**——
    「招标 9 条 pct=100、中标 3 条 pct=33.3」容易被读成「中标占 33%」。
    所以同时算一个诚实的 ``share`` 给机器读（JSON / run_meta），
    模板继续用 ``pct`` 画条。

    ``skip`` 里的标签不参与峰值与合计计算（但行本身保留，两个比例照算）。

    被 skip 的行算出来可能 >100：金额分档里「N/A 10 条」对「已知金额 1 条」
    就是 1000%，直接当条形宽度会溢出容器、进 JSON 也是坏值。所以封顶 100，
    语义是「不参与比较，看旁边的说明」，而不是「占满全宽」。
    """
    skip = skip or set()
    counted = [int(row.get("count") or 0) for row in rows if str(row.get("label")) not in skip]
    peak = max(counted, default=0)
    total = sum(counted)
    for row in rows:
        count = int(row.get("count") or 0)
        row["pct"] = min(100.0, round(count / peak * 100, 1)) if peak else 0
        row["share"] = min(100.0, round(count / total * 100, 1)) if total else 0
    return rows



def _safe_url(value: object) -> str:
    """模板里兜底：非 http(s) 一律输出 ``#``。

    检索层已经过滤过，但模板是最后一道防线——报告会被转发、会被别人改模板，
    不能指望上游每一处都记得校验。
    """
    url = str(value or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else "#"


def _environment(autoescape: bool) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,   # 模板里写错字段名直接报错，不静默出空格
        # HTML 必须转义：标题与原文片段都是从网页抓的，含 & < > 时会直接破坏结构；
        # Markdown 反而不能转义，否则标题里的尖括号会变成 &lt; 印在报告里。
        autoescape=autoescape,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["cell"] = cell
    env.filters["amount"] = fmt_amount
    env.filters["thousands"] = thousands
    env.filters["safe_url"] = _safe_url
    return env


def _meta_with_defaults(meta: dict[str, Any]) -> dict[str, Any]:
    """合并期的默认值（不是模板契约的一部分，属报告版本兼容）。"""
    out = dict(meta)
    kept_total = out.get("kept_total")
    defaults = (
        ("preset", None),
        ("incremental", None),
        ("sources", None),
        ("notify", None),
        ("award_links", 0),
        ("stage_filtered", 0),
        ("only_new", False),
        ("window_total", kept_total),
        ("shown", kept_total or 0),
    )
    for key, value in defaults:
        out.setdefault(key, value)
    return out


def _payload(context: "ReportContext | dict[str, Any]") -> dict[str, Any]:
    data = ReportContext.coerce(context).as_dict()
    data["meta"] = _meta_with_defaults(data["meta"])
    return data


def render_report(
    context: "ReportContext | dict[str, Any]", fmt: str = DEFAULT_FORMAT
) -> str:
    if fmt == "docx":
        raise ValueError("docx 是二进制格式，请用 write_reports 生成")
    if fmt not in TEMPLATES:
        raise ValueError(f"未知格式 {fmt!r}，可选：{'、'.join(FORMATS)}")
    return (
        _environment(autoescape=fmt == "html")
        .get_template(TEMPLATES[fmt])
        .render(**_payload(context))
    )


def render_markdown(context: "ReportContext | dict[str, Any]") -> str:
    return render_report(context, "md")


def write_reports(
    context: "ReportContext | dict[str, Any]", out_dir: Path, fmt: str = DEFAULT_FORMAT
) -> list[Path]:
    """按 fmt 写出报告，返回实际写出的路径。

    ``both`` 保持历史语义 = html + md（兼容旧命令）；``all`` = html + md + docx。
    """
    if fmt == "both":
        formats = ["html", "md"]
    elif fmt == "all":
        formats = list(FORMATS)
    elif fmt in FORMATS:
        formats = [fmt]
    else:
        raise ValueError(f"未知格式 {fmt!r}，可选：{'、'.join(FORMATS)}、both、all")

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name in formats:
        target = out_dir / FILENAMES[name]
        if name == "docx":
            # 延迟导入：只有真要 docx 时才加载这一段 XML 拼装代码
            from . import docx_export

            docx_export.write_docx(_payload(context), target)
        else:
            target.write_text(render_report(context, name), encoding="utf-8")
        paths.append(target)
    return paths
