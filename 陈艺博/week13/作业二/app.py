"""ASGI 入口：``uvicorn app:app --port 8000``。

日常更推荐直接运行 ``python run.py``（会打印访问地址、支持 ``--demo``）。
"""

from __future__ import annotations

from backend.main import create_app

app = create_app()
