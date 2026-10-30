"""运行配置：模型、超时、重试预算、数据库路径。

所有密钥只从环境变量（或项目根目录的 .env）读取，代码里不出现明文 key。
环境变量一览见 README.md 与 .env.example。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# .env 是可选的：没装 python-dotenv 时继续走系统环境变量。
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except Exception:  # pragma: no cover - dotenv 缺失不影响主流程
    pass


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value.strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """一次性冻结的运行参数，避免运行中被环境变量悄悄改掉。"""

    # ---- 数据库 ----
    db_path: Path = PROJECT_ROOT / "data" / "chinook.db"

    # ---- 模型 ----
    primary_model: str = "qwen-max"        # 选表 / 生成 / 改写
    summary_model: str = "qwen-plus"       # 结果汇总（便宜、够用）
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key_envs: tuple[str, ...] = ("DASHSCOPE_API_KEY", "OPENAI_API_KEY")
    # with_structured_output 的落地方式：function_calling / json_mode / json_schema
    structured_method: str = "function_calling"
    request_timeout: float = 60.0
    max_retries: int = 2

    # ---- 编排 ----
    max_repair_attempts: int = 3           # 校验失败 + 执行失败共享的修复预算
    max_result_rows: int = 200             # 执行层行数上限
    max_summary_rows: int = 50             # 进入汇总 prompt 的行数上限
    max_cell_chars: int = 2000             # 单个单元格长度上限
    query_timeout_seconds: float = 5.0     # 单条 SQL 执行超时

    # ---- 派生属性 ----
    _api_key: str = field(default="", repr=False, compare=False)

    @property
    def api_key(self) -> str:
        if self._api_key:
            return self._api_key
        for env_name in self.api_key_envs:
            value = os.getenv(env_name, "").strip()
            if value:
                return value
        return ""

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> "Settings":
        db_path = Path(_env_str("SQL_AGENT_DB", str(cls.db_path)))
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path

        return cls(
            db_path=db_path,
            primary_model=_env_str("SQL_AGENT_MODEL", cls.primary_model),
            summary_model=_env_str("SQL_AGENT_SUMMARY_MODEL", cls.summary_model),
            base_url=_env_str(
                "SQL_AGENT_BASE_URL",
                _env_str("OPENAI_BASE_URL", cls.base_url),
            ),
            structured_method=_env_str(
                "SQL_AGENT_STRUCTURED_METHOD", cls.structured_method
            ),
            request_timeout=_env_float("SQL_AGENT_LLM_TIMEOUT", cls.request_timeout),
            max_retries=_env_int("SQL_AGENT_LLM_RETRIES", cls.max_retries),
            max_repair_attempts=_env_int(
                "SQL_AGENT_MAX_REPAIR_ATTEMPTS", cls.max_repair_attempts
            ),
            max_result_rows=_env_int("SQL_AGENT_MAX_ROWS", cls.max_result_rows),
            max_summary_rows=_env_int(
                "SQL_AGENT_MAX_SUMMARY_ROWS", cls.max_summary_rows
            ),
            max_cell_chars=_env_int("SQL_AGENT_MAX_CELL_CHARS", cls.max_cell_chars),
            query_timeout_seconds=_env_float(
                "SQL_AGENT_QUERY_TIMEOUT", cls.query_timeout_seconds
            ),
        )


settings = Settings.from_env()
