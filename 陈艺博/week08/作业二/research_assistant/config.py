"""集中读取两家 API 的 key 与调用参数。"""
import os

import dotenv

_LOADED = False


def _ensure_loaded():
    global _LOADED
    if not _LOADED:
        # 显式允许相对本文件的 .env（可被调用方覆盖）
        dotenv.load_dotenv(dotenv.find_dotenv(usecwd=True))
        _LOADED = True


class ChatConfig:
    """DeepSeek（OpenAI 兼容）调用配置。"""

    base_url = "https://api.deepseek.com"
    model = "deepseek-chat"

    @staticmethod
    def api_key() -> str:
        _ensure_loaded()
        return os.environ.get("DEEPSEEK_API_KEY", "").strip()


class SearchConfig:
    """Bocha web-search 调用配置。"""

    endpoint = "https://api.bocha.cn/v1/web-search"

    @staticmethod
    def api_key() -> str:
        _ensure_loaded()
        return os.environ.get("BOCHA_API_KEY", "").strip()
