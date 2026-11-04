"""observability.py — 消费 astream(updates) 统一打点。

约定：节点函数内部不出现 logger.info，所有日志由此模块统一处理。
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from .config import get_obs_settings
from .models import FinalAnswer

logger = logging.getLogger("sql_agent.workflow")


def _setup_logging():
    settings = get_obs_settings()
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )
        logger.addHandler(handler)


_setup_logging()


def _truncate(value: str, max_len: int) -> str:
    """压缩为单行并截断。"""
    single = " ".join(value.split())
    if len(single) > max_len:
        return single[:max_len] + "..."
    return single


def log_node_update(
    node_name: str,
    update: dict[str, Any],
    elapsed: float,
    total_elapsed: float,
) -> None:
    """从 update 增量中提取关键信息，输出一行 key=value 日志到 stderr。

    不输出完整 rows、schema_context、API key。
    """
    stage = update.get("stage", node_name)
    parts = [f"stage={stage}", f"elapsed={elapsed:.3f}s", f"total={total_elapsed:.3f}s"]

    # 校验信息
    validation = update.get("validation")
    if validation is not None:
        parts.append(f"ok={validation.ok}")
        parts.append(f"code={validation.code}")

    # 执行信息
    execution = update.get("execution")
    if execution is not None:
        parts.append(f"rows={execution.row_count}")
        parts.append(f"truncated={execution.truncated}")

    # SQL（截断）
    sql = update.get("sql")
    if sql:
        parts.append(f"sql={_truncate(sql, 200)}")

    # 错误（截断）
    last_error = update.get("last_error")
    if last_error:
        parts.append(f"error={_truncate(last_error, 100)}")

    # 计数器
    selection_retry = update.get("selection_retry_count")
    if selection_retry is not None:
        parts.append(f"sel_retry={selection_retry}")
    repair_attempts = update.get("repair_attempts")
    if repair_attempts is not None:
        parts.append(f"repair={repair_attempts}")

    logger.info(" | ".join(parts))


class TokenUsageLogger(BaseCallbackHandler):
    """回调补充：LLM token 用量、模型名。自研最小实现，不引入第三方库。"""

    def on_llm_end(self, response, **kwargs) -> None:
        usage = getattr(response, "llm_output", {}).get("token_usage", {})
        if usage:
            model = getattr(response, "llm_output", {}).get("model_name", "unknown")
            logger.info(
                f"model={model} | "
                f"prompt_tokens={usage.get('prompt_tokens', '?')} | "
                f"completion_tokens={usage.get('completion_tokens', '?')} | "
                f"total_tokens={usage.get('total_tokens', '?')}"
            )

    def on_llm_error(self, error, **kwargs) -> None:
        logger.info(f"llm_error={error}")


async def run_workflow(
    question: str,
    catalog,
    agents,
    obs,
) -> FinalAnswer:
    """消费 astream(updates) 统一打点，返回 FinalAnswer。"""
    from .graph import build_graph

    graph = build_graph(catalog, agents).compile()
    config: dict = {}
    if obs.enable_callback_logger:
        config["callbacks"] = [TokenUsageLogger()]

    start_time = time.perf_counter()
    last_time = start_time
    final_answer: FinalAnswer | None = None

    async for chunk in graph.astream(
        {"question": question},
        stream_mode="updates",
        config=config,
    ):
        now = time.perf_counter()
        for node_name, update in chunk.items():
            log_node_update(node_name, update, now - last_time, now - start_time)
            if update.get("answer") is not None:
                final_answer = update["answer"]
        last_time = now

    if final_answer is None:
        final_answer = FinalAnswer(answer="工作流未产生最终答案。")
    return final_answer
