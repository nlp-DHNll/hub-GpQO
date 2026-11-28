"""按当前评价反馈调整正文，保留已核验的来源清单。"""

import re
from collections import Counter
from dataclasses import asdict

from ..clients.deepseek import DeepSeekClient
from ..data_models import ReviewResult, Source
from ..enums import StepName
from ..errors import RunFailure
from ..log.run_logger import RunLogger
from ..tools.report_text import (
    HEADING,
    content_issues,
    report_body,
    source_payload,
    with_sources,
)

PROTECTED_TOKENS = re.compile(r"\[[Ss][0-9]+\]|[+−-]?\d+(?:[.,]\d+)*[%％]?")
TOP_HEADINGS = re.compile(r"^#{1,2}(?:[ \t]|$)", re.MULTILINE)


def _edit_section(body: str, section: str, before: str, after: str) -> str:
    """只在指定章节内替换唯一匹配的片段。"""
    headings = list(HEADING.finditer(body))
    for index, heading in enumerate(headings):
        if heading.group(1).strip() != section:
            continue
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        text = body[start:end]
        if text.count(before) != 1:
            raise RunFailure("调整片段在指定章节内无法唯一定位")
        if TOP_HEADINGS.search(after):
            raise RunFailure("调整片段改动了章节、数字或引用")
        return body[:start] + text.replace(before, after, 1) + body[end:]
    raise RunFailure("调整指定的章节不存在")


def _apply_edits(body: str, edits: object, allowed: set[str]) -> str:
    if not isinstance(edits, list) or not edits:
        raise RunFailure("DeepSeek 未给出可应用的调整片段")
    for edit in edits:
        if not isinstance(edit, dict):
            raise RunFailure("可读性调整需要 JSON 片段对象")
        section, before, after = (edit.get(key) for key in ("section", "before", "after"))
        if (
            not isinstance(section, str)
            or section not in allowed
            or not isinstance(before, str)
            or not before.strip()
            or not isinstance(after, str)
        ):
            raise RunFailure("调整片段与当前可读性反馈不匹配")
        body = _edit_section(body, section, before, after)
    return body


def revise_report(
    month: str,
    draft: str,
    sources: list[Source],
    review: ReviewResult,
    evaluation: StepName,
    logger: RunLogger,
    *,
    client: DeepSeekClient,
) -> str:
    body = report_body(draft)
    data: dict[str, object] = {
        "month": month,
        "draft": body,
        "issues": [asdict(issue) for issue in review.issues],
    }
    if evaluation is StepName.EVALUATE_CONTENT:
        data.update(mode="content", sources=source_payload(sources))
        return with_sources(client.complete_text(StepName.REVISE_REPORT, data, logger=logger), sources)

    data["mode"] = "readability"
    for attempt in range(1, 4):
        response = client.complete_json(StepName.REVISE_REPORT, data, logger=logger)
        try:
            allowed = {issue.section for issue in review.issues}
            revised = _apply_edits(body, response.get("edits"), allowed)
            if Counter(PROTECTED_TOKENS.findall(body)) != Counter(PROTECTED_TOKENS.findall(revised)):
                raise RunFailure("调整片段改动了章节、数字或引用")
            if revised == body:
                raise RunFailure("可读性调整没有改变正文")
            if content_issues(month, revised, sources):
                raise RunFailure("调整后的报告结构或引用不符合要求")
        except RunFailure as error:
            logger.record("revision_rejected", level="WARNING", details={
                "attempt": attempt, "reason": str(error),
            })
            data["retry_reason"] = str(error)
            if attempt == 3:
                raise RunFailure("可读性调整连续 3 次未通过本地检查") from error
            continue
        return with_sources(revised, sources)
    raise AssertionError("可读性调整应在三次尝试内返回或失败")
