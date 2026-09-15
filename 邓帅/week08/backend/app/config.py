"""应用配置:pydantic-settings 读项目根 .env,研究默认参数集中可调。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# week08 根目录(backend/ 的父目录),报告等产物落于此
WEEK08_DIR = Path(__file__).resolve().parents[2]


def _find_env_files() -> list[str]:
    """收集代码位置向上所有 .env(根在前、近的在后,后者覆盖前者)。

    目录链上可能存在多个 .env(如 邓帅/ 与项目根各一份):近的覆盖远的,
    缺失的键(如 BOCHA_API_KEY)自动从更靠项目根的 .env 补全。
    """
    chain = [WEEK08_DIR, *WEEK08_DIR.parents]
    found = [str(d / ".env") for d in chain if (d / ".env").exists()]  # 近 → 远
    return list(reversed(found))


class Settings(BaseSettings):
    """LLM/搜索凭据与研究默认参数(均可用 .env 覆盖)。"""

    # 凭据(项目根 .env,密钥不写入代码)
    api_key: str = ""
    base_url: str = ""
    base_model: str = ""
    bocha_api_key: str = ""

    # 研究参数(默认值见 PRD 4.5)
    max_rounds: int = 5          # 迭代轮数硬上限
    search_budget: int = 30      # 累计搜索次数预算
    max_new_queries: int = 4     # 每轮新增查询上限
    max_read_per_round: int = 6  # 每轮阅读页面上限
    concurrency: int = 3         # 单任务内部并发(抓取/LLM 抽取)
    page_max_chars: int = 24000  # 单页正文截断(~8k tokens 近似)
    fetch_timeout: float = 10.0  # 网页抓取超时(秒)

    model_config = SettingsConfigDict(
        env_file=_find_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
