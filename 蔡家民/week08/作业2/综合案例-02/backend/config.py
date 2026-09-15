# -*- coding: utf-8 -*-
"""集中配置；所有敏感值只从环境变量读取。"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data" / "research"
TEMPLATE_DIR = BASE_DIR / "templates"
load_dotenv(PROJECT_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "")
BOCHA_SEARCH_COUNT = int(os.getenv("BOCHA_SEARCH_COUNT", "6"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./backend/data/research.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
USE_CELERY = os.getenv("USE_CELERY", "0") == "1"
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-this-in-production")
SHARED_PASSWORD_HASH = os.getenv("SHARED_PASSWORD_HASH", "")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
SESSION_TTL_SECONDS = 24 * 60 * 60
LLM_RETRIES = int(os.getenv("LLM_RETRIES", "3"))
FETCH_PAGE_TIMEOUT = float(os.getenv("FETCH_PAGE_TIMEOUT", "12"))
MAX_PAGE_CHARS = int(os.getenv("MAX_PAGE_CHARS", "12000"))

DEPTH_LIMITS = {
    "quick": {"max_rounds": 1, "max_seconds": 120, "max_searches": 3, "max_model_calls": 8},
    "standard": {"max_rounds": 2, "max_seconds": 360, "max_searches": 8, "max_model_calls": 15},
    "deep": {"max_rounds": 3, "max_seconds": 720, "max_searches": 15, "max_model_calls": 24},
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def today_str() -> str:
    return date.today().isoformat()


if __name__ == "__main__":
    ensure_data_dir()
    print("PROJECT_DIR =", PROJECT_DIR)
    print("DATABASE_URL =", DATABASE_URL.split("@")[-1])
    print("MODEL_NAME =", MODEL_NAME)
    print("配置自检 OK")
