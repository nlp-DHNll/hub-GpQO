"""提供用于验证编排的合成资料和确定性的评价结果。"""

from datetime import date

from .data_models import AgentSteps, ReviewIssue, ReviewResult, SearchHit, Source
from .enums import StepName, Topic
from .log.run_logger import RunLogger

SUMMARY_LINE = "本报告用于演示 Agent 的处理流程。"
SOURCE_HEADING = "## 来源清单"
SECTIONS = {
    Topic.POLICY: "ESG 政策、评级与标准动态",
    Topic.INDUSTRY: "行业新闻与最佳实践",
    Topic.COMPANY: "中国神华动态及 ESG 影响与建议",
    Topic.PEERS: "对标企业的 ESG 关键行动",
}


def _search(
    month: str, topics: tuple[Topic, ...], supplement: bool, logger: RunLogger
) -> list[SearchHit]:
    # 两次搜索各提供一条合成线索，供编排演示补搜和证据缺口。
    topic = Topic.INDUSTRY if supplement else Topic.POLICY
    if topic not in topics:
        return []
    return [
        SearchHit(
            topic,
            f"{month} {SECTIONS[topic]}示例",
            f"https://example.invalid/{topic}",
            f"{SECTIONS[topic]}的合成证据，仅供离线演示。",
        )
    ]


def _filter(
    month: str, hits: list[SearchHit], existing: list[Source], logger: RunLogger
) -> list[Source]:
    sources = list(existing)
    urls = {source.url for source in sources}
    for hit in hits:
        if hit.url in urls:
            continue
        urls.add(hit.url)
        sources.append(
            Source(
                f"S{len(sources) + 1:02d}",
                (hit.topic,),
                hit.title,
                "离线合成资料",
                date.fromisoformat(f"{month}-08"),
                hit.url,
                hit.snippet,
            )
        )
    return sources


def _generate(month: str, sources: list[Source], logger: RunLogger) -> str:
    # 初稿故意保留两处问题，分别触发内容修正和可读性修正。
    sections = [
        f"# 中国神华 {month} ESG 月报（离线演示）",
        "> 本文件使用合成资料，供流程检查，不可作为事实依据。",
        f"## 摘要\n\n{SUMMARY_LINE}\n{SUMMARY_LINE}",
    ]
    for topic, heading in SECTIONS.items():
        entries = [f"- [{source.source_id}] {source.excerpt}" for source in sources if topic in source.topics]
        body = "\n".join(entries) if entries else "本主题在离线样例中缺少资料。"
        sections.append(f"## {heading}\n\n{body}")
    return "\n\n".join(sections)


def _content(month: str, draft: str, sources: list[Source], logger: RunLogger) -> ReviewResult:
    if SOURCE_HEADING in draft:
        return ReviewResult(True)
    return ReviewResult(
        False, (ReviewIssue("来源清单", "缺少来源清单", "补齐来源编号、机构、发布日期和链接"),)
    )


def _revise(
    month: str,
    draft: str,
    sources: list[Source],
    review: ReviewResult,
    evaluation: StepName,
    logger: RunLogger,
) -> str:
    if evaluation is StepName.EVALUATE_CONTENT:
        if SOURCE_HEADING in draft:
            return draft
        entries = [
            f"- [{s.source_id}] [{s.title}]({s.url}) · {s.publisher} · {s.published_on.isoformat()}"
            for s in sources
        ]
        return f"{draft}\n\n{SOURCE_HEADING}\n\n" + "\n".join(entries)
    return draft.replace(f"{SUMMARY_LINE}\n{SUMMARY_LINE}", SUMMARY_LINE, 1)


def _readability(draft: str, logger: RunLogger) -> ReviewResult:
    if draft.count(SUMMARY_LINE) < 2:
        return ReviewResult(True)
    return ReviewResult(False, (ReviewIssue("摘要", "有重复句子", "删除重复的摘要句子"),))


OFFLINE_STEPS = AgentSteps(
    search=_search,
    filter_sources=_filter,
    generate_report=_generate,
    evaluate_content=_content,
    revise_report=_revise,
    evaluate_readability=_readability,
)
