"""适合单实例演示的滑动窗口限流器；生产多实例可替换为 Redis 实现。"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_events: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def enforce(request: Request, bucket: str, limit: int, window_seconds: int) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    client = forwarded or (request.client.host if request.client else "unknown")
    key = f"{bucket}:{client}"
    now = time.monotonic()
    with _lock:
        events = _events[key]
        while events and events[0] <= now - window_seconds:
            events.popleft()
        if len(events) >= limit:
            raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")
        events.append(now)
