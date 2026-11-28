"""运行记录：脚本直接跑完流水线时自己写 run.json；无头运行由运行器生成，这里不覆盖。"""

from datetime import datetime
from pathlib import Path

from . import config
from .bridge import contract
from .collect import CollectSpec, read_json, write_json


def write_run_record(
    out_dir: Path,
    spec: CollectSpec,
    *,
    skill_version: str,
    started_at: datetime,
    duration_ms: int,
    usage: dict[str, int],
    search_count: int,
) -> bool:
    """写一份运行记录。运行器写的（无头、交互）不覆盖；自己上次写的可以更新，返回是否写入。"""
    target = out_dir / contract.RUN_RECORD_FILE
    existing = read_json(target, {})
    if existing and existing.get("invocation") != "script":
        return False
    write_json(
        target,
        {
            "schema_version": 1,
            "run_id": out_dir.name,
            "case": spec.case,
            "mode": spec.mode,
            "version": "scripted",
            "skill_version": skill_version,
            "client": spec.client,
            "industry": spec.industry,
            "time_window": {"start": spec.window_start.isoformat(), "end": spec.window_end.isoformat()},
            "model": config.LLM_MODEL,
            "started_at": existing.get("started_at") or started_at.isoformat(),
            "duration_ms": duration_ms,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cost_usd": None,
            "search_count": search_count,
            "invocation": "script",
            "usage_note": "token 数是脚本内筛选与总结的模型调用；单价未知，费用未折算",
        },
    )
    return True
