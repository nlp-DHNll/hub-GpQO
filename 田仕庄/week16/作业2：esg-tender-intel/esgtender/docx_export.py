"""DOCX 导出：用标准库直接拼 OOXML，不引入 python-docx。

为什么不用 python-docx
----------------------
本项目只用到「标题 + 段落 + 表格 + 外链超链接」四件事，python-docx 为此要拉进
``lxml``（编译型依赖，Windows 上装起来最容易失败）。手写 WordprocessingML 的
代价是约 150 行样板，换来零依赖、确定性输出，且包内结构完全可控（测试里能直接
断言 XML，也能用 python-docx 反向验证文件可被解析）。

产出的最小包结构::

    [Content_Types].xml
    _rels/.rels
    word/document.xml
    word/_rels/document.xml.rels     # 仅在需要外链时存在

Word / WPS / LibreOffice / Google Docs 都能打开。字体统一用「微软雅黑」并设置
东亚字体属性，避免 Word 把中文回退成宋体导致标题不齐。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile

# 金额只保留一套实现：网页、Markdown、Word 里同一个数字必须写成一个样。
# 曾经这里抄了一份浮点版本（「1.26 亿」vs「1.26 亿元」，小数位也不同），
# 注释说是为了避开循环依赖——但 render 只在函数内部 import 本模块，
# 顶层 import 根本不成环。
from .render import fmt_amount

BODY_FONT = "微软雅黑"
TABLE_W = 9500  # twips，A4 纵向、左右各 1.8cm 页边距时的可用宽度

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS_HEAD = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">"""
_DOC_RELS_TAIL = "</Relationships>"
_HYPERLINK_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
# 只给 http(s) 生成外链关系。`javascript:` / `file:` 在 Word 里点击会触发安全
# 提示甚至执行，来源又是第三方网页，没有理由把它写进 rels。
_LINK_SCHEMES = ("http://", "https://")


def _run(
    text: str,
    *,
    bold: bool = False,
    size: int = 21,          # 半磅：21 = 10.5pt，与 Word 正文默认字号一致
    color: str | None = None,
) -> str:
    props = [
        f'<w:rFonts w:ascii="{BODY_FONT}" w:hAnsi="{BODY_FONT}" w:eastAsia="{BODY_FONT}"/>',
        f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>',
    ]
    if bold:
        props.append("<w:b/><w:bCs/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    return (
        f"<w:r><w:rPr>{''.join(props)}</w:rPr>"
        f'<w:t xml:space="preserve">{escape(text or "")}</w:t></w:r>'
    )


def _para(
    content: str,
    *,
    align: str | None = None,
    space_before: int = 0,
    space_after: int = 60,
) -> str:
    props = [
        f'<w:spacing w:before="{space_before}" w:after="{space_after}" w:line="288" w:lineRule="auto"/>'
    ]
    if align:
        props.append(f'<w:jc w:val="{align}"/>')
    return f"<w:p><w:pPr>{''.join(props)}</w:pPr>{content}</w:p>"


def _heading(text: str, level: int = 1) -> str:
    size = {1: 32, 2: 26}.get(level, 22)
    return _para(
        _run(text, bold=True, size=size, color="1F2937"),
        space_before=240 if level == 1 else 160,
        space_after=100,
    )


class _Rels:
    """外链登记表：url → rId。同一 url 只登记一次。"""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}

    def id_for(self, url: str) -> str | None:
        """合法 http(s) 返回 rId；其它返回 None，调用方退化成纯文本。"""
        if not url or not url.lower().startswith(_LINK_SCHEMES):
            return None
        if url not in self._ids:
            self._ids[url] = f"rIdLink{len(self._ids) + 1}"
        return self._ids[url]

    def xml(self) -> str:
        body = "".join(
            f'<Relationship Id="{rid}" Type="{_HYPERLINK_REL}" Target={quoteattr(url)} TargetMode="External"/>'
            for url, rid in self._ids.items()
        )
        return f"{_DOC_RELS_HEAD}{body}{_DOC_RELS_TAIL}"

    def __bool__(self) -> bool:
        return bool(self._ids)


def _cell(
    content: str,
    *,
    width: int,
    shaded: bool = False,
    align: str | None = None,
) -> str:
    props = [f'<w:tcW w:w="{width}" w:type="dxa"/>']
    if shaded:
        props.append('<w:shd w:val="clear" w:color="auto" w:fill="F3F4F6"/>')
    props.append('<w:vAlign w:val="center"/>')
    if align:
        props.append(f'<w:jc w:val="{align}"/>')
    return (
        f"<w:tc><w:tcPr>{''.join(props)}</w:tcPr>"
        f"{_para(content, space_after=0)}</w:tc>"
    )


def _fit_widths(widths: list[int]) -> list[int]:
    """把列宽按比例压进可用页宽。

    ``tblLayout=fixed`` 下 Word 完全按 ``gridCol`` 排版，列宽合计一旦超过
    ``TABLE_W``，表格右侧直接顶出页边距（打印时被裁掉）。8 列清单表曾经是
    10120 twips，超了 620。这里做等比缩放而不是断言，改列宽的人不必先算总和。
    """
    total = sum(widths)
    if total <= TABLE_W:
        return widths
    scaled = [max(1, width * TABLE_W // total) for width in widths]
    # 整除会丢一点，补到最宽的那列，保证合计正好等于页宽（差 1 twip 也别超）
    scaled[scaled.index(max(scaled))] += TABLE_W - sum(scaled)
    return scaled


def _table(rows: Iterable[Iterable[str]], widths: list[int]) -> str:
    """rows 里每个单元格已是 run 片段（可含超链接）。首行当表头。"""
    widths = _fit_widths(list(widths))
    border = (
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="4" w:color="D1D5DB"/>'
        '<w:left w:val="single" w:sz="4" w:color="D1D5DB"/>'
        '<w:bottom w:val="single" w:sz="4" w:color="D1D5DB"/>'
        '<w:right w:val="single" w:sz="4" w:color="D1D5DB"/>'
        '<w:insideH w:val="single" w:sz="4" w:color="D1D5DB"/>'
        '<w:insideV w:val="single" w:sz="4" w:color="D1D5DB"/>'
        "</w:tblBorders>"
    )
    props = (
        f'<w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>'
        f"{border}"
        '<w:tblCellMar><w:top w:w="60" w:type="dxa"/><w:left w:w="80" w:type="dxa"/>'
        '<w:bottom w:w="60" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar>'
        "</w:tblPr>"
    )
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
    body: list[str] = []
    for index, row in enumerate(rows):
        cells = [
            _cell(text, width=widths[pos] if pos < len(widths) else 1200, shaded=index == 0)
            for pos, text in enumerate(row)
        ]
        header = '<w:trPr><w:tblHeader/></w:trPr>' if index == 0 else ""
        body.append(f"<w:tr>{header}{''.join(cells)}</w:tr>")
    return (
        f"<w:tbl>{props}<w:tblGrid>{grid}</w:tblGrid>"
        f"{''.join(body)}</w:tbl>"
        + _para("", space_after=0)
    )


def _link(text: str, url: str, rels: _Rels, *, size: int = 18) -> str:
    rid = rels.id_for(url)
    if rid is None:  # 非 http(s)：保留文字，不造危险链接
        return _run(text, size=size, color="1D4ED8")
    return (
        f'<w:hyperlink r:id="{rid}" w:history="1">'
        f"{_run(text, size=size, color='1D4ED8')}</w:hyperlink>"
    )


def build_document(context: dict[str, Any]) -> tuple[str, str | None]:
    """返回 ``(document.xml, document.xml.rels 或 None)``。"""
    meta = context.get("meta") or {}
    stats = context.get("stats") or {}
    records = context.get("records") or []
    trend = context.get("trend") or []
    coverage = context.get("coverage") or {}
    rels = _Rels()

    parts: list[str] = [
        _para(
            _run("ESG / 双碳 / 碳资产 招标情报清单", bold=True, size=40, color="111827"),
            space_after=80,
        ),
        _para(
            _run(
                f"{meta.get('generated_date', '')}　·　窗口近 {meta.get('days', '')} 天"
                f"　·　数据源 {meta.get('provider', '')}"
                f"　·　生成于 {meta.get('generated_at', '')}",
                size=18,
                color="6B7280",
            ),
            space_after=40,
        ),
        _para(_run(f"检索条件：{meta.get('query_label', '')}", size=18, color="374151")),
    ]

    incremental = context.get("incremental") or {}
    if incremental:
        parts.append(
            _para(
                _run(
                    f"增量口径：本期新增 {incremental.get('new', 0)} 条，"
                    f"往期已入库 {incremental.get('seen', 0)} 条（库 {incremental.get('db', '')}）",
                    size=18,
                    color="374151",
                )
            )
        )

    # 漏斗
    funnel = (
        f"原始命中 {meta.get('raw_hits_total', 0)} 次 → 去重后页面 {meta.get('raw_hits', 0)} 个"
        f" → 非采购剔除 {meta.get('not_tender', 0)} → 低于阈值 {meta.get('below_threshold', 0)}"
        f" → 业务重复 {meta.get('duplicates', 0)} → 保留 {stats.get('total', 0)} 条"
    )
    parts.append(_para(_run(funnel, size=18, color="4B5563")))

    # ---- 概览
    parts.append(_heading("一、本期概览"))
    overview_rows = [
        [_run("指标", bold=True, size=18), _run("数值", bold=True, size=18)],
        [_run("有效条数", size=18), _run(str(stats.get("total", 0)), size=18)],
        [_run("已知金额条数", size=18), _run(str(stats.get("amount_known", 0)), size=18)],
        [_run("金额中位数", size=18), _run(str(stats.get("amount_median", "N/A")), size=18)],
        [_run("金额合计（已知部分）", size=18), _run(str(stats.get("amount_sum", "N/A")), size=18)],
        [_run("灰区待复核", size=18), _run(str(stats.get("needs_review", 0)), size=18)],
        [_run("疑似重复待核实", size=18), _run(str(stats.get("suspects", 0)), size=18)],
        [
            _run("清单展示条数", size=18),
            _run(str(meta.get("shown", stats.get("total", 0))), size=18),
        ],
    ]
    parts.append(_table(overview_rows, [2600, 3200]))

    # ---- 赛道分布
    parts.append(_heading("二、赛道分布", 2))
    track_rows = [[_run("赛道", bold=True, size=18), _run("条数", bold=True, size=18)]]
    for item in stats.get("by_track") or []:
        track_rows.append([_run(str(item.get("label", "")), size=18), _run(str(item.get("count", 0)), size=18)])
    parts.append(_table(track_rows, [6000, 1200]))

    # ---- 金额分档
    parts.append(_heading("三、金额分档", 2))
    bucket_rows = [[_run("区间", bold=True, size=18), _run("条数", bold=True, size=18)]]
    for item in stats.get("by_bucket") or []:
        bucket_rows.append([_run(str(item.get("label", "")), size=18), _run(str(item.get("count", 0)), size=18)])
    parts.append(_table(bucket_rows, [4000, 1200]))

    # ---- 时间趋势
    if len(trend) > 1:
        parts.append(_heading("四、时间趋势（季度）", 2))
        trend_rows = [
            [
                _run("季度", bold=True, size=18),
                _run("条数", bold=True, size=18),
                _run("核心", bold=True, size=18),
                _run("扩展", bold=True, size=18),
                _run("已知金额合计", bold=True, size=18),
            ]
        ]
        for item in trend:
            label = str(item.get("label", "")) + (" *" if item.get("partial") else "")
            trend_rows.append(
                [
                    _run(label, size=18),
                    _run(str(item.get("count", 0)), size=18),
                    _run(str(item.get("core", 0)), size=18),
                    _run(str(item.get("extended", 0)), size=18),
                    _run(str(item.get("amount_wan", "N/A")), size=18),
                ]
            )
        parts.append(_table(trend_rows, [1800, 1200, 1200, 1200, 2400]))
        parts.append(
            _para(
                _run(
                    "带 * 的季度不是完整季度（窗口首尾被截断），条数天然偏低。金额列统一为万元。",
                    size=16,
                    color="6B7280",
                )
            )
        )

    # ---- 清单
    parts.append(_heading("五、招标清单"))
    list_rows = [
        [
            _run("#", bold=True, size=16),
            _run("项目名称", bold=True, size=16),
            _run("采购方", bold=True, size=16),
            _run("金额", bold=True, size=16),
            _run("截止", bold=True, size=16),
            _run("阶段", bold=True, size=16),
            _run("赛道", bold=True, size=16),
            _run("相关度", bold=True, size=16),
        ]
    ]
    for index, record in enumerate(records, start=1):
        fields = record.get("fields") or {}
        raw = record.get("raw") or {}
        track = record.get("track") or {}
        stage = record.get("stage") or {}
        title = raw.get("title_clean") or raw.get("title") or ""
        url = (record.get("source") or {}).get("url") or ""
        amount = fields.get("amount_cny")
        amount_text = fmt_amount(amount)
        stage_text = stage.get("label") or ""
        list_rows.append(
            [
                _run(str(index), size=16),
                _link(title, url, rels, size=16) if url else _run(title, size=16),
                _run(str((fields.get("buyer") or {}).get("value") or "—"), size=16),
                _run(amount_text, size=16),
                _run(str((fields.get("deadline") or {}).get("value") or "—"), size=16),
                _run(stage_text, size=16),
                _run(str(track.get("name") or ""), size=16),
                _run(f"{float(track.get('relevance') or 0):.2f}", size=16),
            ]
        )
    parts.append(_table(list_rows, [420, 3000, 1450, 1100, 900, 800, 1230, 600]))

    # ---- 覆盖与缺口
    parts.append(_heading("六、数据覆盖与缺口"))
    for label, value in (
        ("检索 query", coverage.get("queries") or "无"),
        ("检索源", coverage.get("provider") or ""),
        ("失败情况", coverage.get("failures") or ""),
        (
            "边界声明",
            "本清单基于公开检索结果，不代表该窗口内的全部招标项目；未采集联系人等个人信息。",
        ),
    ):
        parts.append(_para(_run(f"{label}：{value}", size=18, color="374151"), space_after=40))

    paragraphs = "".join(parts)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<w:body>"
        f"{paragraphs}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
        'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        "</w:body></w:document>"
    )
    return document, (rels.xml() if rels else None)


def write_docx(context: dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document, rels = build_document(context)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("word/document.xml", document)
        if rels:
            archive.writestr("word/_rels/document.xml.rels", rels)
    return path
