"""Web 层：把 SQL Agent 暴露成前端能调用的 HTTP 接口。"""

from .app import create_app

__all__ = ["create_app"]
