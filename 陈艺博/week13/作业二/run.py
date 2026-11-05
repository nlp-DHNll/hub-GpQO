"""作业二入口：启动 SQL Agent 网页聊天服务。

用法::

    python run.py                  # 正常模式：需要 .env 里配置 API Key
    python run.py --demo           # 离线演示：无需 Key，SQL 仍真实执行
    python run.py --port 9000      # 换端口
    python run.py --reload         # 开发时热重载

浏览器访问 ``http://127.0.0.1:8000``。
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def lan_ip() -> str:
    """猜一个局域网 IP，方便手机/平板访问同一台电脑。"""

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chinook 数据问答 · LangGraph SQL Agent Web 服务"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="离线演示模式：不调用大模型，使用内置安全 SQL 真实查询数据库",
    )
    parser.add_argument("--host", default=None, help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=None, help="监听端口，默认 8000")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="uvicorn 日志级别",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # 必须在 import backend.config 之前设置：配置对象在导入时冻结。
    if args.demo:
        os.environ["SQL_AGENT_WEB_DEMO"] = "1"
    if args.host:
        os.environ["SQL_AGENT_WEB_HOST"] = args.host
    if args.port:
        os.environ["SQL_AGENT_WEB_PORT"] = str(args.port)
    if args.log_level:
        os.environ["SQL_AGENT_LOG_LEVEL"] = args.log_level

    # 保证从任意工作目录启动都能 import backend / sql_agent_lg。
    sys.path.insert(0, str(PROJECT_ROOT))
    os.chdir(PROJECT_ROOT)

    from backend.config import web_settings  # noqa: E402
    from sql_agent_lg.config import settings as agent_settings  # noqa: E402

    host = web_settings.host
    port = web_settings.port
    log_level = args.log_level or os.getenv("SQL_AGENT_LOG_LEVEL", "info").lower()

    mode_text = "离线演示（无需 API Key）" if web_settings.demo_mode else "真实模型"
    local_url = f"http://127.0.0.1:{port}"
    doc_url = f"{local_url}/docs"

    print("=" * 62)
    print("  Chinook 数据问答 · LangGraph SQL Agent")
    print("-" * 62)
    print(f"  模式：{mode_text}")
    print(f"  模型：{agent_settings.primary_model}")
    print(f"  数据库：{agent_settings.db_path}")
    print(f"  本机访问：{local_url}")
    if host in {"0.0.0.0", "::"}:
        print(f"  局域网访问：http://{lan_ip()}:{port}")
    print(f"  接口文档：{doc_url}")
    print("=" * 62)

    if not web_settings.demo_mode and not agent_settings.has_api_key:
        print()
        print("[提示] 没有检测到 API Key：页面能打开，但提问会提示配置。")
        print("       在 作业二/.env 里填写 DEEPSEEK_API_KEY，")
        print("       或改用：python run.py --demo")
        print()

    import uvicorn  # noqa: E402

    try:
        # 使用 import string，--reload 才能正常监视 app.py / backend。
        uvicorn.run(
            "app:app",
            host=host,
            port=port,
            reload=args.reload,
            log_level=log_level,
        )
    except KeyboardInterrupt:  # pragma: no cover
        print("\n服务已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
