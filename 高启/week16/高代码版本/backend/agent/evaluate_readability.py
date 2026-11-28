"""评价摘要、段落组织、表达和重复内容。"""

from ..clients.deepseek import DeepSeekClient
from ..data_models import ReviewResult
from ..enums import StepName
from ..log.run_logger import RunLogger
from ..tools.report_text import BODY_SECTIONS, parse_review, report_body


def evaluate_readability(draft: str, logger: RunLogger, *, client: DeepSeekClient) -> ReviewResult:
    review = client.complete_json(StepName.EVALUATE_READABILITY, {"draft": report_body(draft)}, logger=logger)
    return parse_review(review, allowed_sections=BODY_SECTIONS)
