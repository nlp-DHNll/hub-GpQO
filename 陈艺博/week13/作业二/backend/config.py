"""Web 层配置。

模型 / 数据库 / 修复预算等仍然复用作业一的 ``sql_agent_lg.config.settings``；
这里只放「前端服务」自己的参数（端口、是否演示模式、多轮改写开关等）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .paths import AGENT_ROOT, PROJECT_ROOT

# 先加载作业二自己的 .env，再让作业一的 config 读取环境变量。
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(AGENT_ROOT / ".env", override=False)
except Exception:  # pragma: no cover - dotenv 缺失不影响主流程
    pass

from sql_agent_lg.config import settings as agent_settings  # noqa: E402


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value.strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass(frozen=True)
class WebSettings:
    host: str = "127.0.0.1"
    port: int = 8000
    demo_mode: bool = False
    contextualize: bool = True          # 有历史对话时，是否先把追问改写成独立问题
    max_history_turns: int = 6          # 送给追问改写器的最近轮数
    max_ui_rows: int = 200              # 返回给前端展示的最大行数
    title: str = "Chinook 数据问答"
    version: str = "1.0.0"

    @classmethod
    def from_env(cls) -> "WebSettings":
        return cls(
            host=_env_str("SQL_AGENT_WEB_HOST", cls.host),
            port=_env_int("SQL_AGENT_WEB_PORT", cls.port),
            demo_mode=_env_bool("SQL_AGENT_WEB_DEMO", cls.demo_mode),
            contextualize=_env_bool(
                "SQL_AGENT_WEB_CONTEXTUALIZE", cls.contextualize
            ),
            max_history_turns=_env_int(
                "SQL_AGENT_WEB_HISTORY_TURNS", cls.max_history_turns
            ),
            max_ui_rows=_env_int("SQL_AGENT_WEB_MAX_ROWS", cls.max_ui_rows),
            title=_env_str("SQL_AGENT_WEB_TITLE", cls.title),
            version=_env_str("SQL_AGENT_WEB_VERSION", cls.version),
        )


web_settings = WebSettings.from_env()

# 方便 main.py 一次性 import
db_path: Path = agent_settings.db_path
