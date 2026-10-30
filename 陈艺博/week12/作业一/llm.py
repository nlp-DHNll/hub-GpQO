"""
大模型调用层：图片预处理 → 请求视觉模型 → 解析结构化结果。

对外只暴露三个函数：
    normalize_image(raw)   -> 归一化后的 JPEG bytes
    analyze(raw, model_id) -> 统一的识别结果 dict
    selfcheck(model_id)    -> 连通性自检
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import time
from typing import Any

import requests
from PIL import Image, ImageOps

import config as cfg

# ------------------------------------------------------------------ 图片处理


class ImageError(Exception):
    """图片无法解码（例如 iPhone 的 HEIC 原图）。"""


def normalize_image(raw: bytes, max_side: int | None = None, quality: int | None = None) -> bytes:
    """统一转成 RGB JPEG 并按长边缩放：省 token、省带宽、顺手修正手机照片方向。"""
    max_side = max_side or cfg.MAX_SIDE
    quality = quality or cfg.JPEG_QUALITY
    try:
        im = Image.open(io.BytesIO(raw))
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise ImageError(
            "无法解析这张图片（可能是 iPhone 的 HEIC 格式）。请在手机相机设置里改成「兼容性最佳」，或截图后再上传。"
        ) from exc

    w, h = im.size
    if max(w, h) > max_side:
        scale = max_side / float(max(w, h))
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def image_size(raw: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(raw)) as im:
            return im.size
    except Exception:  # noqa: BLE001
        return (0, 0)


# ------------------------------------------------------------------ 缓存
_CACHE: dict[str, dict] = {}


def cache_key(jpeg: bytes, model_id: str) -> str:
    return hashlib.sha256(jpeg + model_id.encode()).hexdigest()[:24]


def image_fingerprint(jpeg: bytes) -> str:
    return hashlib.sha256(jpeg).hexdigest()[:16]


# ------------------------------------------------------------------ 调用模型


class LLMError(Exception):
    def __init__(self, message: str, status: int | None = None, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


def _post(model_id: str, image_b64: str, timeout: float) -> dict:
    spec = cfg.MODEL_MAP.get(model_id)
    if not spec:
        raise LLMError(f"未知模型：{model_id}", code="unknown_model")

    provider = cfg.PROVIDERS[spec["provider"]]
    key = cfg.api_key(spec["provider"])
    if not key:
        raise LLMError(
            f"{provider['label']} 未配置 API Key（环境变量 {provider['api_key_env']}），请先在 .env 里填写。",
            code="no_api_key",
        )

    base = {
        "model": model_id,
        "messages": cfg.build_messages(image_b64),
        "temperature": 0.1,
        "max_tokens": 900,
    }
    # 参数降级链：不同模型对可选参数的支持程度不一样，
    # 400/422 就往下掉一级，而不是直接判死。
    #   L1  全量：JSON 模式 + 关思考（omni/qwen3 系列支持关思考，实测 12s -> 1.4s）
    #   L2  去掉关思考：老模型不认 enable_thinking
    #   L3  只留必填：完全不认 response_format
    full = {**base, "response_format": {"type": "json_object"}}
    if cfg.DISABLE_THINKING:
        variants = [
            {**full, "enable_thinking": False},
            full,
            base,
        ]
    else:
        variants = [full, base]

    last_err: Exception | None = None
    for idx, body in enumerate(variants):
        is_last = idx == len(variants) - 1
        try:
            resp = requests.post(
                provider["base_url"].rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise LLMError(f"网络请求失败：{exc}", code="network") from exc

        if resp.status_code == 200:
            return resp.json()

        detail = _error_message(resp)
        if resp.status_code in (400, 422) and not is_last:
            last_err = LLMError(detail, resp.status_code, "bad_param")
            continue
        raise LLMError(detail, resp.status_code, _error_code(resp))

    raise last_err or LLMError("请求失败", code="unknown")


def _error_code(resp: requests.Response) -> str:
    try:
        return (resp.json().get("error") or {}).get("code", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def _error_message(resp: requests.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        msg = err.get("message") or resp.text[:300]
    except Exception:  # noqa: BLE001
        msg = resp.text[:300]
    if resp.status_code == 401:
        return f"API Key 无效或已过期（{msg}）"
    if resp.status_code == 404:
        return f"模型不存在或未开通（{msg}）"
    if resp.status_code == 429:
        return f"调用过于频繁或额度不足（{msg}）"
    return f"模型服务返回 {resp.status_code}：{msg}"


def _is_permanently_unavailable(exc: LLMError) -> bool:
    """未开通 / 模型名不存在这类错误，重试没意义，直接把模型摘掉。"""
    return (exc.status or 0) in (403, 404) or exc.code in (
        "access_denied",
        "model_not_found",
        "ModelNotFound",
        "model_not_supported",
    )


def _extract_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise LLMError("模型返回为空", code="empty")
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, list):  # 少数实现返回分段结构
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return (content or "").strip()


# ------------------------------------------------------------------ 解析

_LEVEL_ALIASES = {
    "高风险": ["高风险", "高", "high", "严重", "重大", "高隐患"],
    "中风险": ["中风险", "中", "medium", "中等", "一般隐患"],
    "低风险": ["低风险", "低", "low", "轻微", "较小"],
    "无风险": ["无风险", "无隐患", "none", "safe", "正常", "安全"],
    "非楼道": ["非楼道", "非住宅", "无关", "非场景", "not_corridor", "not a corridor", "其他场景"],
}


def _norm_level(text: str, is_corridor: bool | None = None) -> str:
    t = (text or "").strip()
    for level in ["非楼道", "高风险", "中风险", "低风险", "无风险"]:
        if level in t:
            return level
    low = t.lower()
    for level, keys in _LEVEL_ALIASES.items():
        for k in keys:
            if k in low:
                return level
    if is_corridor is False:
        return "非楼道"
    return "无风险"


def _pick_json(text: str) -> dict | None:
    """从模型输出里挖出 JSON 对象，容忍 ```json 围栏和前后废话。"""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    for candidate in (cleaned, text):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:  # noqa: BLE001
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:  # noqa: BLE001
            pass
    return None


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in ("true", "1", "yes", "是", "有")


def _as_score(v: Any, level: str) -> int:
    try:
        n = int(round(float(v)))
    except Exception:  # noqa: BLE001
        n = {"高风险": 85, "中风险": 55, "低风险": 22, "无风险": 4, "非楼道": 0}[level]
    return max(0, min(100, n))


def _clean_hazards(raw: Any) -> list[dict]:
    out: list[dict] = []
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        return out
    for item in raw[:8]:
        if isinstance(item, str):
            out.append({"name": item, "category": "其他", "severity": "中", "location": "", "reason": ""})
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("type") or item.get("隐患") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "category": str(item.get("category") or item.get("类别") or "其他").strip(),
                "severity": str(item.get("severity") or item.get("等级") or "中").strip(),
                "location": str(item.get("location") or item.get("位置") or "").strip(),
                "reason": str(item.get("reason") or item.get("原因") or "").strip(),
            }
        )
    return out


def parse_result(text: str) -> dict:
    """把模型原始输出规整成前端能直接渲染的结构。"""
    obj = _pick_json(text)
    if obj is None:
        # 兜底：至少把风险等级捞出来
        level = _norm_level(text)
        return {
            "parse_ok": False,
            "is_corridor": level != "非楼道",
            "risk_level": level,
            "risk_score": _as_score(None, level),
            "scene": "",
            "hazards": [],
            "blocked_passage": False,
            "flammable_material": False,
            "evidence": text.strip()[:400],
            "suggestion": "",
            "confidence": 0.5,
            "raw_text": text[:1200],
        }

    is_corridor = obj.get("is_corridor")
    is_corridor = None if is_corridor is None else _as_bool(is_corridor)
    level = _norm_level(str(obj.get("risk_level") or obj.get("风险等级") or ""), is_corridor)
    if level == "非楼道":
        is_corridor = False
    elif is_corridor is None:
        is_corridor = True

    try:
        conf = float(obj.get("confidence", 0.8))
    except Exception:  # noqa: BLE001
        conf = 0.8
    conf = max(0.0, min(1.0, conf))

    return {
        "parse_ok": True,
        "is_corridor": bool(is_corridor),
        "risk_level": level,
        "risk_score": _as_score(obj.get("risk_score"), level),
        "scene": str(obj.get("scene") or obj.get("场景") or "").strip()[:60],
        "hazards": _clean_hazards(obj.get("hazards") or obj.get("隐患") or []),
        "blocked_passage": _as_bool(obj.get("blocked_passage", False)),
        "flammable_material": _as_bool(obj.get("flammable_material", False)),
        "evidence": str(obj.get("evidence") or obj.get("依据") or "").strip()[:600],
        "suggestion": str(obj.get("suggestion") or obj.get("建议") or "").strip()[:400],
        "confidence": conf,
        "raw_text": text[:1200],
    }


# ------------------------------------------------------------------ 主入口


def analyze(raw: bytes, model_id: str | None = None) -> dict:
    """识别一张图。返回带 meta 的结果字典。"""
    model_id = model_id or cfg.DEFAULT_MODEL
    t0 = time.perf_counter()
    jpeg = normalize_image(raw)

    key = cache_key(jpeg, model_id)
    if cfg.ENABLE_CACHE and key in _CACHE:
        cached = dict(_CACHE[key])
        cached["meta"] = {**cached.get("meta", {}), "cached": True, "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
        return cached

    b64 = base64.b64encode(jpeg).decode()
    chain = cfg.fallback_chain(model_id)
    if not chain:
        raise LLMError("没有任何可用模型的 API Key，请先在 .env 中配置。", code="no_api_key")

    errors: list[str] = []
    used = None
    payload: dict | None = None
    for attempt in chain:
        t_call = time.perf_counter()
        try:
            payload = _post(attempt, b64, cfg.REQUEST_TIMEOUT)
            used = attempt
            break
        except LLMError as exc:
            errors.append(f"{attempt}: {exc}")
            # 未开通 / 模型名不对：摘掉这个模型，继续试下一个
            if _is_permanently_unavailable(exc):
                cfg.mark_blocked(attempt, str(exc))
            # Key / 网络问题没必要再换模型
            if exc.code in ("no_api_key", "network") or (exc.status or 0) == 401:
                break
    if payload is None or used is None:
        raise LLMError("；".join(errors) or "调用失败", code="all_failed")

    text = _extract_text(payload)
    result = parse_result(text)
    result["meta"] = {
        "model": used,
        "model_label": cfg.MODEL_MAP[used]["label"],
        "fallback_from": model_id if used != model_id else None,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "usage": payload.get("usage") or {},
        "request_id": payload.get("id", ""),
        "cached": False,
        "image_size": list(image_size(jpeg)),
        "bytes": len(jpeg),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if cfg.ENABLE_CACHE:
        _CACHE[key] = result
    return result


def selfcheck(model_id: str) -> dict:
    """用一张 32x32 纯色小图试探模型是否真的可用（几乎零成本）。"""
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (120, 130, 140)).save(buf, "JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    t0 = time.perf_counter()
    try:
        payload = _post(model_id, b64, min(30.0, cfg.REQUEST_TIMEOUT))
        text = _extract_text(payload)
        return {
            "model": model_id,
            "ok": True,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "sample": text[:60],
        }
    except LLMError as exc:
        if _is_permanently_unavailable(exc):
            cfg.mark_blocked(model_id, str(exc))
        return {"model": model_id, "ok": False, "error": str(exc), "code": exc.code}


# ------------------------------------------------------------------ 保底演示
def mock_result() -> dict:
    """没有 Key 时的演示结果，方便先看前端效果。"""
    return {
        "parse_ok": True,
        "is_corridor": True,
        "risk_level": "高风险",
        "risk_score": 88,
        "scene": "居民楼首层楼梯间（演示数据）",
        "hazards": [
            {
                "name": "电动自行车",
                "category": "电动车",
                "severity": "高",
                "location": "画面右侧贴墙",
                "reason": "整车停放于疏散走道内，电池存在热失控风险",
            },
            {
                "name": "纸箱堆",
                "category": "可燃堆积物",
                "severity": "中",
                "location": "楼梯拐角",
                "reason": "成摞纸箱紧邻楼梯口，一旦引燃将阻断唯一疏散路径",
            },
        ],
        "blocked_passage": True,
        "flammable_material": True,
        "evidence": "【演示模式】画面右侧贴墙停放一辆电动自行车，占用走道约三分之一宽度；楼梯拐角处堆放约四五个纸箱。",
        "suggestion": "立即将电动车移至室外集中充电点，清理楼梯口纸箱，恢复疏散通道畅通。",
        "confidence": 0.92,
        "raw_text": "",
        "meta": {
            "model": "mock",
            "model_label": "演示模式（未配置 Key）",
            "elapsed_ms": 0,
            "usage": {},
            "cached": False,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mock": True,
        },
    }
