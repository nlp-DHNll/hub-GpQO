"""根据核验资料生成月报初稿。"""

from ..clients.deepseek import DeepSeekClient
from ..data_models import Source
from ..enums import StepName
from ..log.run_logger import RunLogger
from ..tools.report_text import source_payload, with_sources


def generate_report(
    month: str,
    sources: list[Source],
    logger: RunLogger,
    *,
    client: DeepSeekClient,
) -> str:
    draft = client.complete_text(
        StepName.GENERATE_REPORT, {"month": month, "sources": source_payload(sources)}, logger=logger,
    )
    return with_sources(draft, sources)
