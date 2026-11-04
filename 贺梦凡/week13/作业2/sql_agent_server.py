"""Chinook 问数页面。

启动后在浏览器打开 http://127.0.0.1:8765 ，输入自然语言问题。
服务把问题交给 LangGraph SQL Agent，并按节点把选表、SQL、校验和查询结果推到页面。
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from langgraph_sql_agent import (
    DEFAULT_DB,
    DEMO_QUESTIONS,
    SQLAgent,
    build_sql_graph,
    iter_question,
)

WEB_ROOT = Path(__file__).resolve().parent / "web"
HOST = "127.0.0.1"
PORT = int(os.getenv("PORT", "8765"))
LOCK = threading.Lock()
AGENT: SQLAgent | None = None
GRAPH = None


def compose_question(message: str, history: list) -> str:
    """把上一轮结论附在追问后面，方便理解「那加拿大呢」这类问题。"""
    if not history:
        return message
    last = history[-1] if isinstance(history[-1], dict) else {}
    previous = str(last.get("question") or "").strip()[:200]
    summary = " ".join(str(last.get("summary") or "").split())[:180]
    if not previous:
        return message
    return f"{message}\n\n这是追问。上一问：{previous}。上一问结论：{summary}"


class ChatHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[web] {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
            return
        if path == "/api/meta":
            agent = AGENT
            self._json(
                200,
                {
                    "model": getattr(agent, "model", ""),
                    "base_url": getattr(agent, "base_url", ""),
                    "tables": list(agent.parser.table_names) if agent else [],
                    "examples": list(DEMO_QUESTIONS),
                },
            )
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._json(404, {"message": "没有这个页面"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/chat":
            self._json(404, {"message": "没有这个接口"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"message": "请求不是 JSON"})
            return
        message = str(body.get("message") or "").strip()
        if not message:
            self._json(400, {"message": "请输入问题"})
            return
        if len(message) > 2000:
            self._json(400, {"message": "问题请控制在 2000 字以内"})
            return
        history = body.get("history") or []
        if not isinstance(history, list):
            history = []
        if GRAPH is None:
            self._json(503, {"message": "SQL Agent 还没准备好"})
            return
        if not LOCK.acquire(blocking=False):
            self._json(409, {"message": "上一个问题还在查询，请稍后再发"})
            return
        try:
            self._stream(compose_question(message, history[-1:]))
        finally:
            LOCK.release()

    def _stream(self, question: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in iter_question(GRAPH, question):
                payload = json.dumps(event, ensure_ascii=False, default=str)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._json(500, {"message": "页面文件缺失"})
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    global AGENT, GRAPH
    print("正在加载 Chinook 和 SQL Agent...")
    AGENT = SQLAgent(DEFAULT_DB)
    GRAPH = build_sql_graph(AGENT)
    server = ThreadingHTTPServer((HOST, PORT), ChatHandler)
    print(f"问数页面: http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
