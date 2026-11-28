"""组装实际运行使用的网页和模型客户端。"""

from collections.abc import Callable
from functools import partial

import httpx

from .clients.ddgs_search import DDGSSearchClient
from .clients.disclosures import DisclosureClient
from .clients.source_pages import SourcePageClient
from .config import load_deepseek_settings
from .data_models import AgentSteps, ResearchSteps, RunEvent, RunResult
from .tools.filter_sources import filter_sources
from .tools.search import search_sources
from .workflow import run_agent, run_source_check


def _research_steps(http: httpx.Client) -> ResearchSteps:
    pages = SourcePageClient(http)
    return ResearchSteps(
        search=partial(
            search_sources, client=DDGSSearchClient(), page_client=pages, disclosures=DisclosureClient(http),
        ),
        filter_sources=partial(filter_sources, client=pages),
    )


def _page_client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(12.0, connect=5.0))


def run_live_source_check(month: str, on_event: Callable[[RunEvent], None]) -> RunResult:
    with _page_client() as http:
        return run_source_check(month, _research_steps(http), on_event=on_event)


def run_live_report(month: str, on_event: Callable[[RunEvent], None]) -> RunResult:
    from openai import OpenAI

    from .agent.evaluate_content import evaluate_content
    from .agent.evaluate_readability import evaluate_readability
    from .agent.generate_report import generate_report
    from .agent.revise_report import revise_report
    from .clients.deepseek import DeepSeekClient

    settings = load_deepseek_settings()
    with (
        OpenAI(api_key=settings.api_key, base_url=settings.base_url, timeout=90, max_retries=0) as sdk,
        _page_client() as http,
    ):
        research = _research_steps(http)
        client = DeepSeekClient(sdk, settings.model)
        steps = AgentSteps(
            search=research.search,
            filter_sources=research.filter_sources,
            generate_report=partial(generate_report, client=client),
            evaluate_content=partial(evaluate_content, client=client),
            revise_report=partial(revise_report, client=client),
            evaluate_readability=partial(evaluate_readability, client=client),
        )
        return run_agent(month, steps, on_event=on_event)
