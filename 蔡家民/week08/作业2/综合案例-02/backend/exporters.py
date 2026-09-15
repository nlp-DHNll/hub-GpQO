# -*- coding: utf-8 -*-
"""把结构化报告导出为 Markdown、独立 HTML 和 PDF。"""
from __future__ import annotations

import html
from io import BytesIO

from .models import Conclusion, ResearchRecord


def _conclusion_text(item: Conclusion) -> str:
    refs = " ".join(f"[{index + 1}]" for index, _ in enumerate(item.sources))
    suffix = " **（模型推断）**" if item.is_model_inference or not item.sources else ""
    return f"{item.text}{(' ' + refs) if refs else ''}{suffix}"


def to_markdown(rec: ResearchRecord) -> str:
    report = rec.report
    if report is None:
        raise ValueError("报告尚未完成")
    lines = [f"# {report.title}", "", f"> 信息截止：{rec.confidence.info_cutoff if rec.confidence else '未知'} · 置信度：{rec.confidence.overall if rec.confidence else 'low'}", "",
             "## 摘要", "", report.summary, "", "## 背景", "", f"本报告围绕“{rec.topic}”展开，面向{rec.audience}。", ""]
    for section in report.sections:
        lines.extend([f"## {section.heading}", "", section.body, ""])
    lines.extend(["## 关键结论", ""])
    lines.extend(f"- {_conclusion_text(item)}" for item in report.key_conclusions)
    lines.extend(["", "## 风险与局限", ""])
    notes = rec.confidence.notes if rec.confidence else ["资料不足，置信度较低。"]
    lines.extend(f"- {note}" for note in notes)
    if rec.limited:
        lines.append(f"- 研究提前收敛：{rec.limit_reason}")
    lines.extend(["", "## 遗留问题", ""])
    lines.extend(f"- {item}" for item in report.open_questions)
    lines.extend(["", "## 来源列表", ""])
    for index, source in enumerate(rec.sources, 1):
        lines.append(f"{index}. [{source.title or source.url}]({source.url}) — 访问于 {source.accessed_at}（{source.extraction_status}）")
    return "\n".join(lines).strip() + "\n"


def to_html(rec: ResearchRecord) -> str:
    markdown = to_markdown(rec)
    try:
        import markdown as md
        body = md.markdown(markdown, extensions=["extra", "sane_lists"])
    except ImportError:
        body = f"<pre>{html.escape(markdown)}</pre>"
    title = html.escape(rec.report.title if rec.report else rec.topic)
    return f"""<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>{title}</title><style>
@page{{size:A4;margin:18mm}}body{{font-family:-apple-system,BlinkMacSystemFont,'Noto Sans CJK SC','Microsoft YaHei',sans-serif;max-width:880px;margin:40px auto;padding:0 28px;color:#172033;line-height:1.8}}h1{{font-size:32px}}h2{{margin-top:32px;border-bottom:1px solid #dce3ef;padding-bottom:8px}}a{{color:#2463eb;overflow-wrap:anywhere}}blockquote{{background:#f2f6ff;border-left:4px solid #2463eb;padding:8px 16px;margin-left:0}}pre{{white-space:pre-wrap;font:inherit}}@media print{{body{{margin:0;max-width:none}}}}
</style></head><body>{body}</body></html>"""


def to_pdf(rec: ResearchRecord) -> bytes:
    """优先以自包含 HTML 渲染；缺少 Pango 的 Windows 环境使用 ReportLab 降级。"""
    try:
        from weasyprint import HTML
        target = BytesIO()
        HTML(string=to_html(rec)).write_pdf(target)
        return target.getvalue()
    except (ImportError, OSError):
        return _reportlab_pdf(rec)


def _reportlab_pdf(rec: ResearchRecord) -> bytes:
    from pathlib import Path
    from xml.sax.saxutils import escape

    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/simsun.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf"),
    ]
    font = "Helvetica"
    for candidate in candidates:
        if candidate.exists():
            try:
                pdfmetrics.registerFont(TTFont("CJK", str(candidate), subfontIndex=0))
                font = "CJK"
                break
            except Exception:  # pragma: no cover - 继续尝试下一个系统字体
                continue
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("CJKNormal", parent=styles["BodyText"], fontName=font, fontSize=10.5, leading=18, alignment=TA_LEFT)
    heading = ParagraphStyle("CJKHeading", parent=styles["Heading2"], fontName=font, fontSize=16, leading=24, spaceBefore=15)
    title = ParagraphStyle("CJKTitle", parent=styles["Title"], fontName=font, fontSize=24, leading=32)
    target = BytesIO()
    doc = SimpleDocTemplate(target, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm,
                            title=rec.report.title if rec.report else rec.topic)
    report = rec.report
    if report is None:
        raise ValueError("报告尚未完成")
    story = [Paragraph(escape(report.title), title), Spacer(1, 8), Paragraph(escape(report.summary), normal)]
    for section in report.sections:
        story.extend([Paragraph(escape(section.heading), heading), Paragraph(escape(section.body).replace("\n", "<br/>"), normal)])
    story.append(Paragraph("关键结论", heading))
    story.append(ListFlowable([ListItem(Paragraph(escape(_conclusion_text(item)), normal)) for item in report.key_conclusions], bulletType="bullet"))
    story.append(Paragraph("风险与局限", heading))
    story.append(ListFlowable([ListItem(Paragraph(escape(note), normal)) for note in (rec.confidence.notes if rec.confidence else ["资料有限。"])], bulletType="bullet"))
    story.append(Paragraph("来源列表", heading))
    for index, source in enumerate(rec.sources, 1):
        story.append(Paragraph(escape(f"[{index}] {source.title or source.url} — {source.url}"), normal))
    doc.build(story)
    return target.getvalue()
