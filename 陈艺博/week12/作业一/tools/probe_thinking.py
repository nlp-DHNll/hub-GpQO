"""试探 qwen3.8-omni-flash 是否支持关闭思考链（enable_thinking），以及提速幅度。"""
import base64
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import requests
from PIL import Image

import config as cfg

# 用一张小图（长边 640）压成本
im = Image.open(r"E:\八斗学院\Week12_2026Q2\02-多模态大模型\pingpong.jpg").convert("RGB")
im.thumbnail((640, 640))
buf = io.BytesIO()
im.save(buf, "JPEG", quality=85)
b64 = base64.b64encode(buf.getvalue()).decode()

msgs = [
    {"role": "system", "content": "你是楼道消防检查员，只输出 JSON。"},
    {"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        {"type": "text", "text": '判断是否为楼道场景，输出 {"is_corridor":true/false,"risk_level":"高风险/中风险/低风险/无风险/非楼道"}'},
    ]},
]

VARIANTS = [
    ("baseline", {}),
    ("enable_thinking=false", {"enable_thinking": False}),
    ("thinking_budget=0", {"thinking_budget": 0}),
    ("reasoning_effort=none", {"reasoning_effort": "none"}),
]

for name, extra in VARIANTS:
    body = {
        "model": "qwen3.8-omni-flash",
        "messages": msgs,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
        **extra,
    }
    t0 = time.perf_counter()
    try:
        r = requests.post(
            cfg.PROVIDERS["dashscope"]["base_url"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {cfg.api_key('dashscope')}"},
            json=body,
            timeout=90,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[{name}] EXC {exc}")
        continue
    dt = (time.perf_counter() - t0) * 1000
    if r.status_code != 200:
        print(f"[{name}] HTTP {r.status_code} {dt:.0f}ms -> {r.text[:220]}")
        continue
    j = r.json()
    u = j.get("usage") or {}
    det = u.get("completion_tokens_details") or {}
    content = (j["choices"][0]["message"]["content"] or "").replace("\n", " ")[:110]
    print(f"[{name}] OK {dt:.0f}ms | prompt={u.get('prompt_tokens')} completion={u.get('completion_tokens')} "
          f"reasoning={det.get('reasoning_tokens')}\n    -> {content}")
