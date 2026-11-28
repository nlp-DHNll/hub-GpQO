"""月报标题、引用和模型评价的数据规则。"""

import re
from dataclasses import asdict
from html import escape

from ..data_models import ReviewIssue, ReviewResult, Source
from ..errors import RunFailure

BODY_SECTIONS = (
    "摘要",
    "ESG 政策、评级与标准动态",
    "行业新闻与最佳实践",
    "中国神华动态及 ESG 影响与建议",
    "对标企业的 ESG 关键行动",
)
HEADING = re.compile(r"^##[ \t]+([^\n]+)$", re.MULTILINE)
SOURCE_HEADING = re.compile(r"^##[ \t]+来源清单[ \t]*$", re.MULTILINE)
CITATION = re.compile(r"\[([Ss][0-9]+)\]")
BODY_LINK = re.compile(r"https?://|\]\(|^\s*\[[^\]\n]+\]\s*:", re.IGNORECASE | re.MULTILINE)


def source_payload(sources: list[Source]) -> list[dict[str, object]]:
    """转换成模型可读取的资料记录，保留原文和核验日期。"""
    return [asdict(source) | {"published_on": source.published_on.isoformat()} for source in sources]


def report_body(markdown: str) -> str:
    """取出由模型撰写的正文。来源清单由程序生成。"""
    return SOURCE_HEADING.split(markdown, maxsplit=1)[0].rstrip()


def _literal(value: str) -> str:
    """网页标题和发布机构按文本写入 Markdown。"""
    return escape(value).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def with_sources(markdown: str, sources: list[Source]) -> str:
    """用核验资料生成来源清单和正文引用的 Markdown 链接。"""
    rows = ["## 来源清单", ""]
    for source in sources:
        rows.append(
            f"- **{source.source_id}** {_literal(source.title)} · "
            f"{_literal(source.publisher)} · {source.published_on.isoformat()} · [原文](<{source.url}>)"
        )
    rows.append("")
    rows.extend(f"[{source.source_id}]: <{source.url}>" for source in sources)
    return f"{report_body(markdown)}\n\n" + "\n".join(rows).rstrip()


def render_source_check(month: str, sources: list[Source]) -> str:
    """为资料核验模式排版原文、发布日期和证据摘录。"""
    lines = [f"# 中国神华 {month} 资料核验清单", "", "> 本清单供检索步骤验收。"]
    for source in sources:
        topics = "、".join(str(topic) for topic in source.topics)
        lines.extend((
            "",
            f"## {source.source_id} {escape(source.title)}",
            "",
            f"- 发布机构：{escape(source.publisher)}",
            f"- 发布日期：{source.published_on.isoformat()}",
            f"- 原文：<{source.url}>",
            f"- 主题：{topics}",
            "",
            f"> {escape(source.excerpt)}",
        ))
    return "\n".join(lines)


def content_issues(month: str, markdown: str, sources: list[Source]) -> tuple[ReviewIssue, ...]:
    """先检查能由程序确定的标题、章节和引用问题。"""
    body = report_body(markdown)
    issues = []
    if not re.search(rf"^# 中国神华 {re.escape(month)} ESG 月报[ \t]*$", body, re.MULTILINE):
        issues.append(ReviewIssue("全文", "标题缺少正确的企业和月份", f"标题用「中国神华 {month} ESG 月报」"))
    headings = tuple(heading.strip() for heading in HEADING.findall(body))
    if headings != BODY_SECTIONS:
        issues.append(ReviewIssue("全文", "章节缺失、重复或顺序不符", f"按顺序使用：{'、'.join(BODY_SECTIONS)}"))
    cited = {source_id.upper() for source_id in CITATION.findall(body)}
    unknown = cited - {source.source_id for source in sources}
    if unknown:
        issues.append(ReviewIssue("全文", f"存在未核验的引用：{'、'.join(sorted(unknown))}", "用资料中的编号引用证据"))
    if sources and not cited:
        issues.append(ReviewIssue("全文", "正文缺少来源引用", "在有证据支持的关键事实后附来源编号"))
    if BODY_LINK.search(body):
        issues.append(ReviewIssue("全文", "正文含有独立链接", "正文使用 [S01] 格式，链接由程序生成"))
    return tuple(issues)


def parse_review(value: dict[str, object], *, allowed_sections: tuple[str, ...]) -> ReviewResult:
    """核对评价 JSON 的字段和结论，保证失败项有具体建议。"""
    passed, raw_issues = value.get("passed"), value.get("issues")
    if not isinstance(passed, bool) or not isinstance(raw_issues, list) or passed == bool(raw_issues):
        raise RunFailure("DeepSeek 评价格式错误，需要布尔型 passed 和与结论一致的 issues")

    issues = []
    for item in raw_issues:
        if not isinstance(item, dict):
            raise RunFailure("DeepSeek 评价问题应为 JSON 对象")
        section, problem, suggestion = (item.get(key) for key in ("section", "problem", "suggestion"))
        if (
            not isinstance(section, str)
            or section.strip() not in allowed_sections
            or not isinstance(problem, str)
            or not problem.strip()
            or not isinstance(suggestion, str)
            or not suggestion.strip()
        ):
            raise RunFailure("DeepSeek 评价问题需要有效的章节、问题和修改建议")
        issues.append(ReviewIssue(section.strip(), problem.strip(), suggestion.strip()))
    return ReviewResult(passed, tuple(issues))
