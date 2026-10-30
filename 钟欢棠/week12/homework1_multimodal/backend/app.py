"""FastAPI 后端：接收前端上传的楼道照片，调用视觉大模型做风险识别。

启动：
    pip install -r requirements.txt
    uvicorn app:app --host 0.0.0.0 --port 8000

前端页面直接由本服务托管，访问 http://<本机IP>:8000/ 即可。
手机端访问需用 https 或同一局域网下的 http（localhost 视为安全上下文，可调用摄像头）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from multimodal import RiskReport, analyze_image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("safety-api")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="楼道消防安全风险识别", version="1.0.0")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "model": settings.model}


@app.post("/api/analyze", response_model=RiskReport)
async def analyze(file: UploadFile = File(...)) -> RiskReport:
    """接收图片文件，返回结构化风险报告。"""

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"图片过大，超过 {settings.max_upload_bytes // 1024 // 1024}MB 限制",
        )

    mime_type = file.content_type or "image/jpeg"
    logger.info("received image content_type=%s bytes=%d", mime_type, len(data))
    try:
        report = analyze_image(data, mime_type)
    except Exception as exc:  # noqa: BLE001
        logger.exception("analyze failed")
        raise HTTPException(status_code=502, detail=f"模型调用失败：{exc}") from exc

    logger.info("risk_level=%s confidence=%.2f", report.risk_level, report.confidence)
    return report


# 托管前端静态页面（放在路由最后，避免覆盖 /api 路径）。
if FRONTEND_DIR.exists():
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")
