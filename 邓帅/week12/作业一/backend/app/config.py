"""应用配置:pydantic-settings 读目录链上的 .env,LLM 调用参数集中可调。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 作业一根目录(backend/ 的父目录),目录链向上找 .env 的起点
HW12_DIR = Path(__file__).resolve().parents[2]
# backend 目录
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _find_env_files() -> list[str]:
    """收集代码位置向上所有 .env(根在前、近的在后,后者覆盖前者)。

    目录链上可能存在多个 .env(如 邓帅/ 与项目根各一份):近的覆盖远的,
    缺失的键自动从更靠项目根的 .env 补全。
    """
    chain = [HW12_DIR, *HW12_DIR.parents]
    found = [str(d / ".env") for d in chain if (d / ".env").exists()]  # 近 → 远
    return list(reversed(found))


class Settings(BaseSettings):
    """LLM 凭据与调用参数(均可用 .env 覆盖)。"""

    # 凭据(项目根 .env,密钥不写入代码)
    api_key: str = ""
    base_url: str = ""
    base_model: str = ""

    # workflow 参数
    llm_timeout: float = 30.0  # 单次模型调用超时上限(秒,S7:超时即终止不重试)

    model_config = SettingsConfigDict(
        env_file=_find_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
