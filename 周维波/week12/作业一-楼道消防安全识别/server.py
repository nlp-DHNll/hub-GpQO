# -*- coding: utf-8 -*-
"""楼道消防安全识别 —— 后端服务（纯标准库 HTTP 服务）

启动：python server.py
前端静态文件位于 ./frontend，接口：
  GET  /                前端页面
  GET  /api/health      服务与密钥状态
  POST /api/analyze     图片风险识别 {provider?, image(data URL/base64)}
"""

import json
import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# 控制台/日志统一 UTF-8，避免重定向后中文乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
CONFIG_PATH = BASE_DIR / "config.json"
ENV_PATH = BASE_DIR / ".env"

# ---------- .env 加载（不依赖第三方库） ----------
def load_dotenv(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv(ENV_PATH)

# ---------- 配置 ----------
def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


CONFIG = load_config()
_LEVEL_MAP = {
    "高风险": "high",
    "中风险": "medium",
    "低风险": "low",
    "无风险": "none",
    "非楼道": "non_stairwell",
}


def api_key_for(provider: str) -> str:
    spec = CONFIG["providers"][provider]
    return os.environ.get(spec.get("api_key_env", ""), "").strip()


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ---------- HTTP Handler ----------
class Handler(BaseHTTPRequestHandler):
    server_version = "StairwellRisk/1.0"

    # ---------- 通用 ----------
    def _json(self, obj: dict, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path, content_type: str):
        if not path.is_file():
            self._json({"ok": False, "error": "not found"}, 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        if fmt.startswith("POST") or "404" in str(args):
            print(f"[{time.strftime('%H:%M:%S')}] {fmt % args}", flush=True)

    # ---------- 路由 ----------
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_file(FRONTEND_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/style.css":
            self._serve_file(FRONTEND_DIR / "style.css", "text/css; charset=utf-8")
        elif path == "/app.js":
            self._serve_file(FRONTEND_DIR / "app.js", "application/javascript; charset=utf-8")
        elif path == "/api/health":
            self._handle_health()
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/analyze":
            self._handle_analyze()
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    # ---------- 健康检查 ----------
    def _handle_health(self):
        keys = {}
        for name, spec in CONFIG["providers"].items():
            keys[name] = {
                "label": spec["name"],
                "model": spec["model"],
                "configured": bool(api_key_for(name)),
            }
        self._json({
            "ok": True,
            "provider": CONFIG.get("provider", "deepseek"),
            "providers": list(CONFIG["providers"].keys()),
            "keys": keys,
        })

    # ---------- 识别接口 ----------
    def _handle_analyze(self):
        import llm

        length = int(self.headers.get("Content-Length", 0) or 0)
        max_body = CONFIG.get("max_body_bytes", 15 * 1024 * 1024)
        if length <= 0 or length > max_body:
            self._json({"ok": False, "error": f"请求体过大或为空（上限 {max_body // 1024 // 1024} MB）"}, 413)
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json({"ok": False, "error": "请求不是合法的 JSON"}, 400)
            return

        provider = str(body.get("provider") or CONFIG.get("provider", "deepseek")).strip().lower()
        if provider not in list(CONFIG["providers"].keys()) + ["mock"]:
            self._json({"ok": False, "error": f"不支持的模型提供商: {provider}"}, 400)
            return
        image = body.get("image") or body.get("image_url") or ""
        if not image:
            self._json({"ok": False, "error": "缺少图片字段 image（base64 data URL）"}, 400)
            return

        try:
            norm_url, norm_bytes = llm.normalize_image(
                image,
                max_bytes=CONFIG.get("max_image_bytes", 15 * 1024 * 1024),
                max_edge=CONFIG.get("max_edge", 1568),
                quality=CONFIG.get("image_quality", 88),
            )
        except llm.ImageError as e:
            self._json({"ok": False, "error": str(e)}, 400)
            return

        try:
            spec = CONFIG["providers"].get(provider) or {}
            api_key = "" if provider == "mock" else api_key_for(provider)
            result = llm.classify(provider, norm_url, spec, api_key)
        except llm.LlmError as e:
            self._json({"ok": False, "error": str(e)}, 502)
            return
        except Exception as e:
            self._json({"ok": False, "error": f"服务内部错误：{e}"}, 500)
            return

        category = result["category"]
        self._json({
            "ok": True,
            "category": category,
            "level": _LEVEL_MAP.get(category, "unknown"),
            "reason": result["reason"],
            "provider": provider,
            "model": result["model"],
            "latency_ms": result["latency_ms"],
            "image_bytes": norm_bytes,
        })
        print(
            f"[{time.strftime('%H:%M:%S')}] 识别完成 provider={provider} "
            f"category={category} latency={result['latency_ms']}ms image={norm_bytes // 1024}KB",
            flush=True,
        )


# ---------- 启动 ----------
def main():
    host = CONFIG.get("host", "0.0.0.0")
    port = int(CONFIG.get("port", 8000))
    server = None
    while port < port + 100:
        try:
            server = ThreadingHTTPServer((host, port), Handler)
            break
        except OSError:
            port += 1
    if server is None:
        print("端口都被占用，无法启动", flush=True)
        sys.exit(1)

    server.daemon_threads = True
    print("=" * 56, flush=True)
    print("  楼道消防安全风险识别服务已启动", flush=True)
    print(f"  本机访问:   http://127.0.0.1:{port}", flush=True)
    print(f"  手机访问:   http://{lan_ip()}:{port}  （需在同一局域网）", flush=True)
    print("-" * 56, flush=True)
    for name, spec in CONFIG["providers"].items():
        status = "已配置" if api_key_for(name) else "未配置密钥（前端将无法调用，可先用演示模式）"
        print(f"  {spec['name']:<20} model={spec['model']:<24} {status}", flush=True)
    print("=" * 56, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止", flush=True)


if __name__ == "__main__":
    main()
