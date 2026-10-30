"""项目启动脚本 —— 打印访问地址并启动 uvicorn 服务。"""

import socket
import sys

# Windows 控制台 UTF-8 支持
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import uvicorn
from backend.config import HOST, PORT


def get_lan_ip() -> str:
    """通过 UDP socket 连接公网 DNS 获取本机出口 IP（局域网地址）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    lan_ip = get_lan_ip()

    print("=" * 52)
    print("   🧯 楼道消防安全隐患识别服务")
    print("=" * 52)
    print(f"  本机访问 : http://127.0.0.1:{PORT}/")
    print(f"  手机访问 : http://{lan_ip}:{PORT}/   （同一 WiFi）")
    print(f"  接口文档 : http://127.0.0.1:{PORT}/docs")
    print("=" * 52)
    print()

    uvicorn.run(
        "backend.app:app",
        host=HOST,
        port=PORT,
        reload=False,
    )