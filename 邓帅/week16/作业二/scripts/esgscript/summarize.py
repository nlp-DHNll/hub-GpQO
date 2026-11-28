"""总结：用固定提示词让模型依据结构化数据起草分析，写进 analysis.json。

智能体可以在此基础上改写结论与建议；没有 analysis.json 时 build 直接用初稿。
"""

import time
from pathlib import Path
from typing import Any

from . import prompts
from .bridge import contract
from .collect import WORK_DIR, CollectSpec, _add_usage, add_stage_time, read_json, write_json
from .llm import LLM
from .stats import bid_stats

ANALYSIS_FILE = "analysis.json"

MONTHLY_KEYS = (
    "summary",
    "policy",
    "industry",
    "company_facts",
    "advice",
    "benchmark_intro",
    "benchmark",
    "watchlist",
    "method_notes",
)
BID_KEYS = ("opening", "topic_notes", "amount_notes", "trend_notes", "buyer_notes", "typical_notes")
DAILY_KEYS = ("highlights",)


def draft(out_dir: Path, spec: CollectSpec, *, force: bool = False) -> dict[str, Any]:
    """起草分析并写入 analysis.json；已存在且不强制时不重写（保留智能体的改写）。"""
    target = out_dir / ANALYSIS_FILE
    if target.is_file() and not force:
        cached = read_json(target, {})
        return cached if isinstance(cached, dict) else {}
    data = read_json(out_dir / contract.DATA_FILE, {})
    result: Any = {}
    started = time.perf_counter()
    with LLM() as llm:
        if spec.case == "monthly-report":
            usable = [item for item in data.get("evidence", []) if item["verification"] == "verified"]
            keys: tuple[str, ...] = MONTHLY_KEYS
            if usable:
                result = llm.json(*prompts.monthly_draft(spec, usable))
        elif spec.mode == "summary":
            records = data.get("records", [])
            keys = BID_KEYS
            if records:
                result = llm.json(*prompts.bid_draft(records, bid_stats(records, quarterly=spec.days > 180)))
        else:
            keys = DAILY_KEYS
            if data.get("records"):
                result = llm.json(*prompts.daily_draft(data["records"]))
        usage = llm.usage.as_dict()
    _add_usage(out_dir / WORK_DIR, usage)
    add_stage_time(out_dir / WORK_DIR, "draft_s", time.perf_counter() - started)
    analysis = {key: result.get(key) if isinstance(result, dict) else None for key in keys}
    analysis["benchmark"] = analysis.get("benchmark") if isinstance(analysis.get("benchmark"), list) else []
    write_json(target, analysis)
    return analysis
