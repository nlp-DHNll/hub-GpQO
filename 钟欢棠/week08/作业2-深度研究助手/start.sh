#!/usr/bin/env bash
# 启动深度研究助手后端（在项目根目录运行，自动加载 .env）
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
echo "启动后端：http://127.0.0.1:${PORT}  （/health 健康检查）"
uvicorn backend.app:app --host 127.0.0.1 --port "${PORT}" --reload
