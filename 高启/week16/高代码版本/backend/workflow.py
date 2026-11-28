"""编排搜索、生成、评价和保存步骤。"""

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from .config import DEFAULT_LOG_DIR, DEFAULT_REPORT_DIR, MAX_REPAIR_ROUNDS
from .data_models import (
    AgentSteps,
    ResearchSteps,
    ReviewResult,
    RunEvent,
    RunResult,
    Source,
)
from .enums import StepName, Topic
from .errors import RunFailure
from .run_tracking import AgentRun, run_with_logging
from .tools.report_text import render_source_check
from .tools.save_report import save_report


def run_agent(
    month: str,
    steps: AgentSteps,
    *,
    log_dir: Path = DEFAULT_LOG_DIR,
    reports_dir: Path = DEFAULT_REPORT_DIR,
    on_event: Callable[[RunEvent], None] | None = None,
) -> RunResult:
    """执行检索、生成、双阶段评价与 Markdown 保存。"""

    def execute(run: AgentRun) -> Path:
        sources = _collect_sources(month, run, steps)
        with run.step(StepName.GENERATE_REPORT) as logger:
            draft = steps.generate_report(month, sources, logger)
            _save_draft(month, draft, reports_dir, run, logger)

        draft = _review_and_repair(StepName.EVALUATE_CONTENT, month, draft, sources, run, steps, reports_dir)
        draft = _review_and_repair(StepName.EVALUATE_READABILITY, month, draft, sources, run, steps, reports_dir)

        with run.step(StepName.SAVE_REPORT):
            return save_report(month, draft, reports_dir)

    return run_with_logging(month, execute, log_dir=log_dir, on_event=on_event)


def _collect_sources(month: str, run: AgentRun, steps: ResearchSteps) -> list[Source]:
    """首轮搜索所有主题，第二轮只补搜尚未取得可靠资料的主题。"""
    missing = tuple(Topic)
    sources: list[Source] = []
    candidate_count = 0
    for attempt in (1, 2):
        with run.step(StepName.SEARCH, attempt=attempt) as logger:
            hits = steps.search(month, missing, attempt == 2, logger)
            candidate_count += len(hits)
            logger.record("search_results", details={"topics": list(missing), "count": len(hits)})
        with run.step(StepName.FILTER_SOURCES, attempt=attempt) as logger:
            sources = steps.filter_sources(month, hits, sources, logger)
            covered = {topic for source in sources for topic in source.topics}
            missing = tuple(topic for topic in Topic if topic not in covered)
            logger.record("sources_filtered", details={"count": len(sources), "missing": list(missing)})
        if not missing:
            break
    if not sources:
        if candidate_count == 0:
            raise RunFailure("搜索和补搜均未返回候选网页，请查看日志中的搜索和栏目结果")
        raise RunFailure("补搜后仍没有可用资料，请检查搜索服务或更换月份后重试")
    return sources


def run_source_check(
    month: str,
    steps: ResearchSteps,
    *,
    log_dir: Path = DEFAULT_LOG_DIR,
    reports_dir: Path = DEFAULT_REPORT_DIR / "sources",
    on_event: Callable[[RunEvent], None] | None = None,
) -> RunResult:
    """单独运行检索和筛选，输出可供人工核对的资料清单。"""
    def execute(run: AgentRun) -> Path:
        sources = _collect_sources(month, run, steps)
        markdown = render_source_check(month, sources)
        with run.step(StepName.SAVE_SOURCE_LIST):
            return save_report(month, markdown, reports_dir)

    return run_with_logging(month, execute, log_dir=log_dir, on_event=on_event)


def _review_failure(evaluation: StepName, review: ReviewResult) -> RunFailure:
    label = "内容" if evaluation is StepName.EVALUATE_CONTENT else "可读性"
    lines = [f"已用完 {MAX_REPAIR_ROUNDS} 轮修正，{label}评价仍未通过。"]
    for issue in review.issues:
        lines.append(f"- {issue.section}：{issue.problem}。建议：{issue.suggestion}")
    return RunFailure("\n".join(lines))


def _save_draft(month: str, draft: str, reports_dir: Path, run: AgentRun, logger) -> None:
    """保存每次有效稿件，便于回看评价前后到底改了什么。"""
    path = save_report(month, draft, reports_dir / "drafts" / run.state.run_id)
    logger.record("draft_saved", details={"path": path, "repair_round": run.state.repair_round})


def _review_and_repair(
    evaluation: StepName,
    month: str,
    draft: str,
    sources: list[Source],
    run: AgentRun,
    steps: AgentSteps,
    reports_dir: Path,
) -> str:
    """在当前评价阶段复评和修正，两阶段共用运行状态中的修正轮数。"""
    while True:
        with run.step(evaluation) as logger:
            if evaluation is StepName.EVALUATE_CONTENT:
                review = steps.evaluate_content(month, draft, sources, logger)
            else:
                review = steps.evaluate_readability(draft, logger)
            details: dict[str, object] = {"passed": review.passed}
            if review.issues:
                details["issues"] = [asdict(issue) for issue in review.issues]
            logger.record("review_result", details=details)

        if review.passed:
            return draft
        if run.state.repair_round >= MAX_REPAIR_ROUNDS:
            raise _review_failure(evaluation, review)

        # 初次评价不计轮次，只有实际开始修正才加一。
        with run.step(StepName.REVISE_REPORT, repair_round=run.state.repair_round + 1) as logger:
            logger.record("revision_requested", details={"evaluation": evaluation})
            draft = steps.revise_report(month, draft, sources, review, evaluation, logger)
            _save_draft(month, draft, reports_dir, run, logger)
