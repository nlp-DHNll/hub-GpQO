"""FastAPI 应用 —— 提供 REST API 并托管前端 index.html。"""

from io import BytesIO
import traceback

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from PIL import Image

from backend.config import FRONTEND_DIR, MAX_UPLOAD_MB
from backend.risk_prompt import (
    SYSTEM_PROMPT,
    build_user_prompt,
    parse_and_normalize,
)
from backend.qwen_service import load_model, is_ready, generate

app = FastAPI(
    title="楼道消防安全隐患识别",
    description="上传楼道照片，调用 Qwen2.5-VL-3B-Instruct 自动识别消防安全隐患并输出风险等级。",
    version="1.0.0",
)

# CORS（作业场景允许跨域调试，生产环境需收窄）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """启动时在后台线程加载模型，失败仅日志不崩溃。"""
    try:
        await run_in_threadpool(load_model)
    except Exception:
        print("[启动] 模型加载失败，请检查路径和依赖：")
        traceback.print_exc()
        print("[启动] 服务将继续运行，但推理接口暂时不可用。")


# ── 健康检查 ──────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "model_ready": is_ready()}


# ── 推理接口 ──────────────────────────────────────────────

@app.post("/api/risk/analyze")
async def analyze_risk(file: UploadFile = File(...)):
    """上传楼道图片，返回消防安全隐患分析结果。字段名必须为 file。"""

    # 校验 Content-Type
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(400, detail="请上传图片文件（image/jpeg 或 image/png）")

    # 读取
    data = await file.read()
    if not data:
        raise HTTPException(400, detail="上传的文件为空，请重新选择图片。")

    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, detail=f"图片大小超过 {MAX_UPLOAD_MB}MB 限制，请压缩后重试。")

    if not is_ready():
        raise HTTPException(503, detail="模型尚未加载完成，请稍后重试。")

    # 打开图片
    try:
        image = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(400, detail="无法解析图片文件，请确认文件未损坏。")

    width, height = image.size
    user_prompt = build_user_prompt(width, height)

    # 推理（阻塞函数通过 run_in_threadpool 调用）
    try:
        raw = await run_in_threadpool(
            generate, image, SYSTEM_PROMPT, user_prompt
        )
    except Exception:
        traceback.print_exc()
        raise HTTPException(500, detail="模型推理异常，请稍后重试。")

    # 解析 + 归一化
    parsed = parse_and_normalize(raw)

    filename = file.filename or "unknown.jpg"

    return {
        "success": True,
        "filename": filename,
        **parsed,
    }


# ── 前端页面（必须写在所有 /api/... 之后） ────────────────

@app.get("/")
def serve_frontend():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(404, detail="前端页面 index.html 不存在，请确认 frontend/index.html 文件已创建。")
    return FileResponse(str(index_path))