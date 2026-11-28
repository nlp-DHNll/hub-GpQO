"""核对报告结构和引用，并评价事实与分析是否有依据。"""

from ..clients.deepseek import DeepSeekClient
from ..data_models import ReviewResult, Source
from ..enums import StepName
from ..log.run_logger import RunLogger
from ..tools.report_text import (
    BODY_SECTIONS,
    content_issues,
    parse_review,
    report_body,
    source_payload,
)


def evaluate_content(
    month: str,
    draft: str,
    sources: list[Source],
    logger: RunLogger,
    *,
    client: DeepSeekClient,
) -> ReviewResult:
    issues = content_issues(month, draft, sources)
    if issues:
        return ReviewResult(False, issues)

    review = client.complete_json(
        StepName.EVALUATE_CONTENT,
        {"month": month, "draft": report_body(draft), "sources": source_payload(sources)},
        logger=logger,
    )
    return parse_review(review, allowed_sections=(*BODY_SECTIONS, "全文"))
