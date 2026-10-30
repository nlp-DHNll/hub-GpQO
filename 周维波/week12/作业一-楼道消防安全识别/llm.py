# -*- coding: utf-8 -*-
"""模型调用层：图片归一化 + 调用 deepseek-flash / qwen-vl-max / 演示模式"""

import base64
import io
import time

import requests
from PIL import Image

from prompt import MOCK_RESULT, TASK_PROMPT, SYSTEM_PROMPT, parse_response

# 防止解压炸弹：超大像素图片直接拒绝
Image.MAX_IMAGE_PIXELS = 50_000_000


class ImageError(Exception):
    """图片处理失败"""


class LlmError(Exception):
    """模型调用失败"""


def normalize_image(data_url: str, max_bytes: int = 15 * 1024 * 1024,
                    max_edge: int = 1568, quality: int = 88):
    """接收 data URL 或裸 base64，解码 → 校验 → 缩放到 max_edge → 重新编码 JPEG。

    返回 (data_url, 字节数)。缩放的目的是控制请求体大小、节省模型 token 与费用。
    """
    if data_url.startswith("data:"):
        header, _, b64 = data_url.partition(",")
        if ";" in header:
            mime = header[5:header.find(";")]
        else:
            mime = header[5:]
    else:
        b64 = data_url
        mime = "image/jpeg"

    if not b64:
        raise ImageError("图片数据为空")
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        raise ImageError("图片不是合法的 base64 编码")
    if not raw:
        raise ImageError("图片数据为空")
    if len(raw) > max_bytes:
        raise ImageError(f"图片过大（{len(raw) // 1024 // 1024} MB），请压缩后重试")

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        img = img.convert("RGB")
    except Image.DecompressionBombError:
        raise ImageError("图片像素尺寸过大，请压缩后重试")
    except Exception as e:
        raise ImageError(f"图片解码失败：{e}")

    w, h = img.size
    scale = min(1.0, max_edge / max(w, h))
    if scale < 1.0:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    out = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{out}", len(buf.getvalue())


def _call_openai_compatible(spec: dict, api_key: str, image_data_url: str, timeout: int = 60) -> str:
    """以 OpenAI 兼容格式调用任意视觉模型（DeepSeek / 阿里云百炼等）"""
    url = spec["base_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": spec["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {"type": "text", "text": TASK_PROMPT},
                ],
            },
        ],
        "temperature": 0.2,
        "max_tokens": 512,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if resp.status_code != 200:
        detail = resp.text[:300] if resp.text else f"HTTP {resp.status_code}"
        raise LlmError(f"模型接口返回 {resp.status_code}：{detail}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LlmError(f"模型返回结构异常：{str(data)[:300]}")


def classify(provider: str, image_data_url: str, spec: dict, api_key: str) -> dict:
    """对一张图片做楼道风险识别。

    返回 {"category": 五档之一, "reason": str, "model": str}
    """
    t0 = time.time()
    if provider == "mock":
        category, reason = MOCK_RESULT
        return {
            "category": category,
            "reason": reason,
            "model": "mock-demo",
            "latency_ms": round((time.time() - t0) * 1000),
        }
    if not api_key:
        raise LlmError(
            f"未配置 {spec['name']} 的 API Key（环境变量 {spec['api_key_env']} 为空）。"
            f"请在项目 .env 中填写后重启服务，或在前端切换到演示模式。"
        )
    text = _call_openai_compatible(spec, api_key, image_data_url)
    category, reason = parse_response(text)
    return {
        "category": category,
        "reason": reason,
        "model": spec["model"],
        "latency_ms": round((time.time() - t0) * 1000),
    }
