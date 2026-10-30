"""日志配置：默认输出到 stderr，保证 CLI 的 stdout 只有干净 JSON。"""

from __future__ import annotations

import logging
import os
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"


def configure_logging(level: str | None = None) -> None:
    log_level = (level or os.getenv("SQL_AGENT_LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format=LOG_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
        force=True,
    )
    # 第三方 HTTP 日志太吵，只留告警。
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
