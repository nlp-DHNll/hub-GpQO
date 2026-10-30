# app/config.py

import os
from pathlib import Path


# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# 模型路径
MODEL_PATH = Path(r"models\Qwen--Qwen3-VL-8B-Instruct").resolve()


# 图片上传大小限制：10 MB
MAX_UPLOAD_SIZE_BYTES = int(
    os.getenv(
        "MAX_UPLOAD_SIZE_BYTES",
        str(10 * 1024 * 1024),
    )
)


# 允许上传的 MIME 类型
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}


# 允许的实际图片格式
ALLOWED_IMAGE_FORMATS = {
    "JPEG",
    "PNG",
    "WEBP",
}


# FastAPI 服务配置
HOST = os.getenv("HOST", "0.0.0.0")

PORT = int(
    os.getenv("PORT", "8000")
)
