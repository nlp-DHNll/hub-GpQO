"""
楼道消防安全隐患识别 · 后端服务
FastAPI + 多模态大模型（OpenAI 兼容接口）

启动：
    python run.py             # 默认 8000 端口
    python run.py --https     # 手机摄像头需要 https 时使用（自签证书）
"""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config as cfg
import llm

app = FastAPI(title="楼道消防安全隐患识别", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HISTORY_FILE = cfg.RESULT_DIR / "history.jsonl"
_history_lock = threading.Lock()
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 手机原图一般 2~8MB


# ------------------------------------------------------------------ 静态资源
app.mount("/static", StaticFiles(directory=str(cfg.STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(cfg.UPLOAD_DIR)), name="uploads")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(cfg.STATIC_DIR / "index.html")


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(cfg.STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


# ------------------------------------------------------------------ 元信息
@app.get("/api/health")
def health() -> dict[str, Any]:
    models = cfg.available_models()
    ready = [m for m in models if m["available"]]
    return {
        "ok": True,
        "models_ready": len(ready),
        "models_total": len(models),
        "default_model": cfg.DEFAULT_MODEL,
        "mock_mode": not ready,
        "cache": cfg.ENABLE_CACHE,
        "max_side": cfg.MAX_SIDE,
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/api/models")
def models() -> dict[str, Any]:
    models = cfg.available_models()
    ready = [m for m in models if m["available"]]
    return {
        "models": models,
        "default": cfg.DEFAULT_MODEL if cfg.model_available(cfg.DEFAULT_MODEL) else (ready[0]["id"] if ready else ""),
        "mock_mode": not ready,
    }


@app.get("/api/selfcheck")
def selfcheck(model: str | None = Query(default=None)) -> dict[str, Any]:
    """逐个模型试探，确认 Key 与模型名是否真的可用。"""
    targets = [model] if model else [m["id"] for m in cfg.available_models() if m["available"]]
    if not targets:
        return {"results": [], "hint": "未检测到任何 API Key，请先在 .env 里填写 DASHSCOPE_API_KEY。"}
    return {"results": [llm.selfcheck(m) for m in targets]}


# ------------------------------------------------------------------ 识别
@app.post("/api/analyze")
async def analyze(
    image: UploadFile = File(..., description="待识别的图片"),
    model: str = Form(default=""),
    mock: int = Form(default=0),
    save: int = Form(default=1),
) -> JSONResponse:
    raw = await image.read()
    if not raw:
        raise HTTPException(400, "上传内容为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "图片超过 15MB，请压缩后重试")

    model_id = (model or "").strip() or cfg.DEFAULT_MODEL
    if model and model not in cfg.MODEL_MAP:
        raise HTTPException(400, f"不支持的模型：{model}")

    # 演示模式：不调用模型，直接回一份样例结果，方便先看前端效果
    if mock:
        result = llm.mock_result()
        entry = _save(raw, result, save=bool(save))
        result["meta"]["history_id"] = entry["id"]
        return JSONResponse({"ok": True, "data": result})

    if cfg.blocked_reason(model_id):
        raise HTTPException(
            400,
            f"模型 {model_id} 当前不可用：{cfg.blocked_reason(model_id)}。请在下拉框换一个模型，或去控制台确认已开通。",
        )

    if not cfg.model_available(model_id):
        raise HTTPException(
            503,
            "尚未配置模型 API Key。请把 Key 填入项目根目录的 .env（DASHSCOPE_API_KEY=sk-xxx）后重启服务。",
        )

    try:
        result = llm.analyze(raw, model_id)
    except llm.ImageError as exc:
        raise HTTPException(400, str(exc)) from exc
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc

    entry = _save(raw, result, save=bool(save))
    result["meta"]["history_id"] = entry["id"]
    return JSONResponse({"ok": True, "data": result})


@app.post("/api/analyze/batch")
async def analyze_batch(
    images: list[UploadFile] = File(...),
    model: str = Form(default=""),
) -> JSONResponse:
    """批量识别（一次最多 9 张），用于评测与巡检。"""
    if len(images) > 9:
        raise HTTPException(400, "一次最多 9 张图片")
    out = []
    for f in images:
        try:
            raw = await f.read()
            result = llm.analyze(raw, model or cfg.DEFAULT_MODEL)
            out.append({"filename": f.filename, "ok": True, "data": result})
        except (llm.LLMError, llm.ImageError) as exc:
            out.append({"filename": f.filename, "ok": False, "error": str(exc)})
    return JSONResponse({"ok": True, "items": out})


# ------------------------------------------------------------------ 历史记录
def _save(raw: bytes, result: dict, save: bool = True) -> dict:
    """落盘原图 + 追加一条历史记录。"""
    entry_id = time.strftime("%Y%m%d%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    jpeg = b""
    try:
        jpeg = llm.normalize_image(raw)
    except llm.ImageError:
        jpeg = raw

    fname = ""
    if save:
        fname = f"{entry_id}.jpg"
        (cfg.UPLOAD_DIR / fname).write_bytes(jpeg)

    meta = result.get("meta", {})
    entry = {
        "id": entry_id,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "risk_level": result.get("risk_level", ""),
        "risk_score": result.get("risk_score", 0),
        "scene": result.get("scene", ""),
        "evidence": result.get("evidence", ""),
        "suggestion": result.get("suggestion", ""),
        "hazards": result.get("hazards", []),
        "model": meta.get("model", ""),
        "model_label": meta.get("model_label", ""),
        "elapsed_ms": meta.get("elapsed_ms", 0),
        "image": fname,
        "mock": bool(meta.get("mock")),
    }
    with _history_lock:
        with HISTORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    result.setdefault("meta", {})["history_id"] = entry_id
    return entry


@app.get("/api/history")
def history(limit: int = Query(default=30, ge=1, le=200)) -> dict[str, Any]:
    if not HISTORY_FILE.exists():
        return {"items": [], "stats": {}}
    lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()[-400:]
    items = []
    for line in reversed(lines):
        try:
            items.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    stats: dict[str, int] = {}
    for it in items:
        stats[it.get("risk_level", "未知")] = stats.get(it.get("risk_level", "未知"), 0) + 1
    return {"items": items[:limit], "stats": stats, "total": len(items)}


@app.delete("/api/history")
def clear_history() -> dict[str, Any]:
    with _history_lock:
        if HISTORY_FILE.exists():
            HISTORY_FILE.unlink()
    return {"ok": True}


# ------------------------------------------------------------------ 工具
def lan_ip() -> str:
    """猜一下本机在局域网里的 IP，方便手机访问。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


if __name__ == "__main__":
    import uvicorn

    print(f"本机访问： http://127.0.0.1:{cfg.PORT}")
    print(f"手机访问： http://{lan_ip()}:{cfg.PORT}")
    uvicorn.run(app, host=cfg.HOST, port=cfg.PORT, log_level="info")
