"""存放 Agent 各步骤之间传递的数据类。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .enums import RunStatus, StepName, StepStatus, Topic

if TYPE_CHECKING:
    from .log.run_logger import RunLogger


@dataclass(frozen=True)
class DeepSeekSettings:
    """DeepSeek SDK 需要的凭据、服务地址和模型名称。"""

    api_key: str = field(repr=False)  # 密钥不出现在配置对象的文本表示中。
    base_url: str
    model: str


@dataclass(frozen=True)
class SearchHit:
    """网页搜索返回的一条待核验线索。"""

    topic: Topic  # 本次搜索针对的主题。
    title: str
    url: str
    snippet: str  # 搜索结果摘要，供后续核验时参考。
    provider: str = ""  # 发现线索的检索入口，用于统计每个入口的核验结果。


@dataclass(frozen=True)
class Source:
    """核验过发布日期和原文后，可用于报告引用的一条资料。"""

    source_id: str  # 报告中的引用编号，例如 S01。
    topics: tuple[Topic, ...]  # 同一资料可能支持多个主题。
    title: str
    publisher: str
    published_on: date  # 原文发布日期，用于筛选目标月份。
    url: str
    excerpt: str  # 从原文提取的相关证据。


@dataclass(frozen=True)
class ReviewIssue:
    """评价发现的一个问题，用于指导下一次调整。"""

    section: str  # 问题所在章节，涉及全文时写「全文」。
    problem: str  # 当前版本存在的问题。
    suggestion: str  # 对应的修改建议。


@dataclass(frozen=True)
class ReviewResult:
    """一次内容评价或可读性评价的结果。"""

    passed: bool  # 报告是否通过本次评价。
    issues: tuple[ReviewIssue, ...] = ()  # 待修改的问题及建议。


@dataclass(frozen=True)
class ResearchSteps:
    """搜索和筛选的接口，完整工作流和资料核验共用。"""

    # 搜索参数依次为月份、主题、是否补搜、日志。
    search: Callable[[str, tuple[Topic, ...], bool, RunLogger], list[SearchHit]]
    # 筛选步骤接收本次线索与此前核验通过的资料，返回合并去重后的资料。
    filter_sources: Callable[[str, list[SearchHit], list[Source], RunLogger], list[Source]]


@dataclass(frozen=True)
class AgentSteps(ResearchSteps):
    """完整 Agent 需要的检索和报告步骤。"""

    generate_report: Callable[[str, list[Source], RunLogger], str]
    evaluate_content: Callable[[str, str, list[Source], RunLogger], ReviewResult]
    # StepName 表示需要修正的是内容评价还是可读性评价的问题。
    revise_report: Callable[
        [str, str, list[Source], ReviewResult, StepName, RunLogger], str
    ]
    evaluate_readability: Callable[[str, RunLogger], ReviewResult]


@dataclass(frozen=True)
class SourcePage:
    """下载后的 HTML 网页原文，用于核验发布日期和正文。"""

    url: str
    body: bytes
    encoding: str | None = None


@dataclass(frozen=True)
class StepState:
    """单次步骤执行的状态，结束后记录用时。"""

    name: StepName
    status: StepStatus
    duration_ms: int | None = None
    attempt: int | None = None  # 搜索次数，可用于区分首次搜索和补搜。


@dataclass(frozen=True)
class RunState:
    """整次 Agent 运行在某个时刻的状态。"""

    run_id: str  # 唯一运行编号，用于关联日志。
    month: str  # 目标报告月份，格式为 YYYY-MM。
    status: RunStatus
    started_at: datetime  # 整次运行的开始时间，仅写入首条日志。
    repair_round: int = 0  # 内容和可读性阶段共用的修正轮次。
    step: StepState | None = None  # 当前或最近执行的步骤。


@dataclass(frozen=True)
class RunEvent:
    """一条可用于写入日志和显示命令行进度的运行事件。"""

    event: str  # 事件名称，例如 step_started。
    state: RunState  # 事件发生时的运行状态。
    level: str = "INFO"
    details: dict[str, object] = field(default_factory=dict)  # 如资料数或失败原因。


@dataclass(frozen=True)
class RunResult:
    """Agent 结束后返回给命令行的结果。"""

    state: RunState  # 包含最终运行状态。
    log_path: Path
    report_path: Path | None = None  # 报告成功保存后才有路径。
    message: str = ""  # 供命令行展示的结果说明。
