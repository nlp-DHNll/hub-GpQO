"""Web 服务入口：python -m sql_agent.web"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 SQL Agent 的 Web 服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument("--reload", action="store_true", help="改代码自动重载（开发用）")
    parser.add_argument(
        "--log-level",
        default=os.getenv("SQL_AGENT_LOG_LEVEL", "INFO"),
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "sql_agent.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level.lower(),
    )


if __name__ == "__main__":
    main()
