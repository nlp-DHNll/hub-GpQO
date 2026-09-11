"""把 Report 渲染成带溯源 / 置信度 / 推断标注的 Markdown。"""
from __future__ import annotations

import re
from typing import Iterable

from .schemas import Report


def _probably_unsourced(text: str) -> bool:
    """结论若不含 [n] 来源标记 → 判为模型推断，需程序标注。"""
    return not re.search(r"\[\d+\]", text or "")


def _collapse_unique(exists: Iterable[str]) -> dict:
    seen: dict = {}
    for x in exists:
        if x and x not in seen:
            seen[x] = True
    return seen


def render_full(report: Report) -> str:
    """渲染完整研究报告（Markdown）。无来源支撑的结论会被程序级标注『(模型推断)』。"""
    topic = report.topic or "(未命名主题)"
    steps = report.process.steps
    ran_real = any(s.hits > 0 for s in steps)
    all_kws = list(_collapse_unique(s.kw for s in steps))
    all_urls = list(_collapse_unique(u for s in steps for u in s.urls))

    lines: list[str] = [f"# 深度研究报告：{topic}", ""]

    # 元信息（置信度口径 / 信息截止 / 过程计数）
    meta = []
    if report.generated_at:
        meta.append(f"报告生成时间：{report.generated_at}")
    if ran_real:
        meta.append(f"检索迭代 {report.process.rounds} 轮 / {len(all_kws)} 组词 / {len(all_urls)} 页")
        meta.append("正文 [n] 下标 = 文末『来源列表』序号；每条结论可溯源核验。")
    else:
        meta.append("本次运行未检索到真实网页来源（多为未配 BOCHA_API_KEY / 桩演示模式）；"
                    "文中标注 *(模型推断)* 的表述为模型推理、非来自真实来源。")
    lines.append("> " + " ｜ ".join(meta))
    lines.append("")

    # 摘要
    lines += ["## 摘要", "", (report.summary or "(暂无摘要——请配置 DEEPSEEK_API_KEY 后重跑。)"), ""]

    # 关键结论（无来源自动追加推断标注）
    lines += ["## 关键结论", ""]
    if report.conclusions:
        for c in report.conclusions:
            tag = " *(模型推断)*" if _probably_unsourced(c) and ran_real else ""
            lines.append(f"- {c}{tag}")
    else:
        lines.append("（无）")
    lines.append("")

    # 分节正文
    lines += ["## 正文", ""]
    body_nodes = [s for s in report.sections if (s.heading or s.body).strip()]
    if body_nodes:
        for sec in body_nodes:
            if sec.heading:
                lines += [f"### {sec.heading}", ""]
            lines.append(sec.body.strip() or "（正文缺失）")
            lines.append("")
    else:
        lines += ["（无正文分节）", ""]

    # 遗留问题
    lines += ["## 遗留问题", ""]
    lines += ([f"- {q}" for q in report.open_questions] if report.open_questions else ["（无）"])
    lines.append("")

    # 来源列表（可追溯）
    lines += ["## 来源列表", ""]
    seen: set[str] = set()
    if report.sources:
        for idx, s in enumerate(report.sources, 1):
            if s.url and s.url in seen:
                continue
            if s.url:
                seen.add(s.url)
            title = s.title or s.url or f"（来源 {idx}）"
            cite = f" [{title}]({s.url})" if s.url else f" {title}"
            src_tail = f" — {s.source}" if s.source else ""
            lines.append(f"{idx}.{cite}{src_tail}")
            if s.summary:
                lines.append(f"   {s.summary}")
    else:
        lines.append("（本次运行无真实来源——桩 / 演示模式）")
    lines.append("")

    # 研究过程记录
    lines += ["## 研究过程记录", ""]
    if steps:
        for st in steps:
            sample = "、".join(st.urls[:3]) + ("…" if len(st.urls) > 3 else "")
            lines.append(f"- 第 {st.round_no} 轮 检索「{st.kw}」命中 {st.hits} 条：{sample}")
    else:
        lines.append("（无检索过程记录）")
    lines.append("")

    lines.append("---")
    lines.append("*置信度说明：带 [n] 下标的结论可由文末来源链接人工核验；"
                 "不带来源下标的表述一律视为模型推断，请结合上下文审慎采信。*")
    return "\n".join(lines)
