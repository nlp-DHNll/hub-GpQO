"""最小化视觉调用自检：用 1x1 图片 + 短提示，确认 Key / 模型名是否可用。"""
import os, sys, base64, io
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv
import requests
from PIL import Image

load_dotenv(os.path.join(ROOT, ".env"))

base = os.getenv("DASHSCOPE_BASE_URL", "").rstrip("/")
key = os.getenv("DASHSCOPE_API_KEY", "")

buf = io.BytesIO()
Image.new("RGB", (32, 32), (120, 130, 140)).save(buf, "JPEG")
b64 = base64.b64encode(buf.getvalue()).decode()

models = sys.argv[1:] or ["qwen3.8-omni-flash"]
for m in models:
    payload = {
        "model": m,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": "这是什么颜色？只回答颜色。"},
        ]}],
        "max_tokens": 20,
    }
    try:
        r = requests.post(base + "/chat/completions",
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json=payload, timeout=60)
        print(f"[{m}] HTTP {r.status_code}")
        if r.status_code == 200:
            j = r.json()
            print("   ->", j["choices"][0]["message"]["content"][:80])
        else:
            print("   ->", r.text[:400])
    except Exception as e:
        print(f"[{m}] EXC", e)
