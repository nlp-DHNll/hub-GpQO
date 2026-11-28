"""Agent 使用的固定主题、步骤名称和状态。"""

from enum import StrEnum


class Topic(StrEnum):
    """搜索和整理月报资料时使用的主题。"""

    POLICY = "policy"  # ESG 政策、评级与标准。
    INDUSTRY = "industry"  # 行业动态与最佳实践。
    COMPANY = "company"  # 中国神华动态。
    PEERS = "peers"  # 对标企业行动。


class RunStatus(StrEnum):
    """整次 Agent 运行的生命周期状态。"""

    INITIALIZING = "initializing"  # 正在准备运行。
    RUNNING = "running"  # 正在执行 Agent 流程。
    SUCCEEDED = "succeeded"  # 报告已成功保存。
    FAILED = "failed"  # 运行因错误或业务条件未达标而结束。
    CANCELLED = "cancelled"  # 运行被用户中断。


class StepName(StrEnum):
    """日志和运行状态中使用的稳定步骤名称。"""

    SEARCH = "search"  # 搜索资料。
    FILTER_SOURCES = "filter_sources"  # 核验、筛选和去重。
    GENERATE_REPORT = "generate_report"  # 生成初稿。
    EVALUATE_CONTENT = "evaluate_content"  # 评价内容。
    REVISE_REPORT = "revise_report"  # 按当前反馈调整报告。
    EVALUATE_READABILITY = "evaluate_readability"  # 评价可读性。
    SAVE_REPORT = "save_report"  # 保存报告。
    SAVE_SOURCE_LIST = "save_source_list"  # 保存阶段核验用的资料清单。


class StepStatus(StrEnum):
    """单次步骤的执行状态。评价步骤完成后，是否通过由评价结果表示。"""

    RUNNING = "running"  # 步骤正在执行。
    COMPLETED = "completed"  # 步骤正常返回了结果。
    FAILED = "failed"  # 步骤执行时发生错误。
    CANCELLED = "cancelled"  # 步骤执行被中断。
