"""Markdown 报告渲染：元信息头、来源列表、给 LLM 看的资料格式化。"""
from __future__ import annotations

from datetime import datetime

from app.models import Source


def build_report_header(
    topic: str,
    created_at: datetime,
    rounds_count: int,
    sources_count: int,
) -> str:
    """在 LLM 输出的报告前加上元信息头（主标题 + 生成时间 + 检索轮数 + 来源数）。"""
    return (
        f"# {topic} · 深度研究报告\n\n"
        f"> 生成时间：{created_at.strftime('%Y-%m-%d %H:%M:%S')}　"
        f"|　检索轮数：{rounds_count}　"
        f"|　来源数：{sources_count}\n\n"
    )


def append_sources_section(markdown: str, sources: list[Source]) -> str:
    """在报告末尾追加来源列表章节（Markdown 链接格式）。"""
    if not sources:
        return markdown + "\n\n---\n\n_（无来源）_\n"
    lines = ["", "---", "", "## 来源列表"]
    for s in sources:
        lines.append(f"[{s.id}] [{s.title}]({s.url})")
    return markdown + "\n".join(lines) + "\n"


def format_sources_for_prompt(sources: list[Source]) -> str:
    """把 Source 列表格式化成 LLM 可读的字符串（用于综合阶段的 prompt）。"""
    lines: list[str] = []
    for s in sources:
        snippet = (s.snippet or "").strip()
        lines.append(f"[{s.id}] {s.title}\n    URL: {s.url}\n    内容: {snippet}")
    return "\n\n".join(lines)
