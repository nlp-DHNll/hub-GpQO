"""DeepSeek + Observability 配置 + 全局常量。"""

import os
from dataclasses import dataclass, field

# 重试预算常量（不进 State）
MAX_REPAIR_ATTEMPTS = 3
MAX_SELECTION_RETRY = 1
MAX_EXECUTION_ROWS = 200
MAX_SUMMARY_ROWS = 50
EXECUTION_TIMEOUT_SEC = 5

# tool_choice 后门，默认 auto
SQL_AGENT_TOOL_CHOICE = "auto"


@dataclass
class DeepSeekSettings:
    """从环境变量读取 DeepSeek 配置，无硬编码 key。"""

    api_key: str = field(default_factory=lambda: os.environ.get("DEEPSEEK_API_KEY", ""))
    base_url: str = field(
        default_factory=lambda: os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
        )
    )
    model: str = "deepseek-chat"  # deepseek-flash 对应 deepseek-chat

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass
class ObservabilitySettings:
    enable_callback_logger: bool = True
    log_level: str = field(
        default_factory=lambda: os.environ.get("SQL_AGENT_LOG_LEVEL", "INFO")
    )


# 单例
_deepseek_settings: DeepSeekSettings | None = None
_obs_settings: ObservabilitySettings | None = None


def get_deepseek_settings() -> DeepSeekSettings:
    global _deepseek_settings
    if _deepseek_settings is None:
        _deepseek_settings = DeepSeekSettings()
    return _deepseek_settings


def get_obs_settings() -> ObservabilitySettings:
    global _obs_settings
    if _obs_settings is None:
        _obs_settings = ObservabilitySettings()
    return _obs_settings
