"""探测当前 API Key 下可用的模型（用于确认视觉模型名称）。"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
from dotenv import load_dotenv
import requests

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

key = os.getenv("DASHSCOPE_API_KEY")
base = os.getenv("DASHSCOPE_BASE_URL", "").rstrip("/")
print("base:", base, "| key:", (key or "")[:8] + "..." if key else None)

r = requests.get(base + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=40)
print("status:", r.status_code)
try:
    data = r.json().get("data", [])
    ids = sorted([m.get("id", "") for m in data])
    print("total:", len(ids))
    kw = ("vl", "ocr", "omni", "visual", "qvq", "deepseek")
    print("--- 视觉相关候选 ---")
    for i in ids:
        if any(k in i.lower() for k in kw):
            print(" ", i)
    print("--- 全部（前 80）---")
    for i in ids[:80]:
        print(" ", i)
except Exception as e:
    print("parse fail:", e, r.text[:500])
