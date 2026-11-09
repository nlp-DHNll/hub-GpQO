"""运行配置。凭据只从环境变量 / 项目根 .env 读取。

与 week12 版的差异：新增 checkpoint_db（SqliteSaver 落盘位置），
多轮会话与回放都依赖它。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 自动向上找到项目根 .env（如 badou2026/.env），子目录运行也生效。
load_dotenv(find_dotenv(usecwd=True))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    db_path: Path = PROJECT_ROOT / "ref" / "chinook.db"
    checkpoint_db: Path = PROJECT_ROOT / "ref" / "checkpoints.sqlite"
    primary_model: str = "qwen3.8-max"
    summary_model: str = "qwen3.8-max"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    max_repair_attempts: int = 3
    max_result_rows: int = 200
    max_summary_rows: int = 50
    max_cell_chars: int = 2000
    query_timeout_seconds: float = 5.0
    max_history_turns: int = 6

    @classmethod
    def from_env(cls) -> Settings:
        def resolve(name: str, default: Path) -> Path:
            path = Path(os.getenv(name, str(default)))
            return path if path.is_absolute() else PROJECT_ROOT / path

        db_path = resolve("SQL_AGENT_DB", cls.db_path)
        checkpoint_db = resolve("SQL_AGENT_CHECKPOINT_DB", cls.checkpoint_db)

        base_model = os.getenv("BASE_MODEL", cls.primary_model)
        return cls(
            db_path=db_path,
            checkpoint_db=checkpoint_db,
            primary_model=os.getenv("SQL_AGENT_MODEL", base_model),
            summary_model=os.getenv("SQL_AGENT_SUMMARY_MODEL", base_model),
            base_url=os.getenv("OPENAI_BASE_URL")
            or os.getenv("BASE_URL", cls.base_url),
            api_key=os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY", ""),
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
            max_history_turns=_env_int(
                "SQL_AGENT_MAX_HISTORY_TURNS", cls.max_history_turns
            ),
        )


settings = Settings.from_env()
