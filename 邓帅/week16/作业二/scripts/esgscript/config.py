"""配置：凭据、模型与常量。密钥只从已被忽略的 .env 读取，任何输出里都不回显。"""

import os
from pathlib import Path

from dotenv import load_dotenv

WEEK16_DIR = Path(__file__).resolve().parents[3]
"""week16 目录：脚本版、工具目录、运行目录都以它为根。"""

load_dotenv(WEEK16_DIR.parent / ".env")

ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
"""智谱 key：值自带 Bearer 前缀，作 Authorization 头原样使用。"""

LLM_API_KEY = os.getenv("API_KEY", "")
LLM_BASE_URL = os.getenv("BASE_URL", "")
LLM_MODEL = os.getenv("BASE_MODEL", "")
"""总结与筛选用的模型：与项目其它作业同一套 OpenAI 兼容接口。"""

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
"""抓取网页与政采网检索用的浏览器标识；政采网对非浏览器标识返回 403。"""

FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"
"""出图用的中文字体；matplotlib 默认字体不含中文。"""
