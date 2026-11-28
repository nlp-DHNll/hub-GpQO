"""集中定义项目路径、工作流常量和 DeepSeek 配置。"""

import os
from datetime import timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .data_models import DeepSeekSettings
from .errors import RunFailure

PROJECT_DIR = Path(__file__).resolve().parents[1]
PROMPT_DIR = PROJECT_DIR / "backend" / "agent" / "prompts"
DEFAULT_LOG_DIR = PROJECT_DIR / "logs"
DEFAULT_REPORT_DIR = PROJECT_DIR / "reports"
REPORT_TIMEZONE = timezone(timedelta(hours=8))
MAX_REPAIR_ROUNDS = 5

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


def load_deepseek_settings() -> DeepSeekSettings:
    """优先读取进程环境变量，其次读取项目根目录的 .env。"""
    from dotenv import dotenv_values

    settings = dotenv_values(PROJECT_DIR / ".env")

    def setting(name: str, default: str = "") -> str:
        return os.getenv(name, "").strip() or (settings.get(name) or "").strip() or default

    key = setting("DEEPSEEK_API_KEY")
    if not key:
        raise RunFailure("请在 .env 中配置 DEEPSEEK_API_KEY")
    base_url = setting("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
    try:
        url = urlsplit(base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None:
            raise ValueError("invalid base URL")
    except ValueError as error:
        raise RunFailure("DEEPSEEK_BASE_URL 应为模型服务的 HTTP 或 HTTPS 地址") from error

    return DeepSeekSettings(key, base_url, setting("DEEPSEEK_MODEL", DEFAULT_MODEL))
