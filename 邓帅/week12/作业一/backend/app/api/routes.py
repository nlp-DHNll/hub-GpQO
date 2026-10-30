"""POST /api/recognize 全流程:校验→base64→调用→归一化→重试→统一错误响应。

技术设计 §2.4(T6 路由内直接 JSONResponse,不自建异常层;T7 非超时故障兜底 502)。
"""
import base64
import logging

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse
from openai import APITimeoutError, OpenAIError

from app import llm
from app.levels import normalize

logger = logging.getLogger(__name__)

router = APIRouter()

# S5 文件约束:类型白名单 + 10MB 上限
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024

# 前端文案同源的功能设计 §7 E 系列(仅作 message,前端有自己的映射)
MSG_INVALID_FILE = "仅支持 jpg/png/webp 图片，且不超过 10MB"
MSG_MODEL_TIMEOUT = "识别超时，请重试"
MSG_MODEL_UNPARSABLE = "识别失败，请重试或换一张照片"


def _error(status: int, code: str, message: str) -> JSONResponse:
    """统一错误响应结构(PRD §6.1)。"""
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )


@router.post("/recognize")
async def recognize(image: UploadFile | None = File(None)) -> JSONResponse:
    # 1. 校验(S5):缺字段/非白名单类型 → 400,不发起模型调用
    if image is None or image.content_type not in ALLOWED_CONTENT_TYPES:
        return _error(400, "INVALID_FILE", MSG_INVALID_FILE)

    # 2. 读 bytes(仅内存,S10 不落盘)→ 大小校验
    data = await image.read()
    await image.close()
    if len(data) > MAX_FILE_SIZE:
        return _error(400, "INVALID_FILE", MSG_INVALID_FILE)

    # 3. base64 data URL(mime 用上传文件自带 content_type)
    data_url = f"data:{image.content_type};base64,{base64.b64encode(data).decode()}"

    # 4-6. 调用 → 归一化 → 未命中原样重试 1 次(S6)
    for _attempt in range(2):
        try:
            raw = await llm.recognize_image(data_url)
        except APITimeoutError:
            return _error(504, "MODEL_TIMEOUT", MSG_MODEL_TIMEOUT)  # 超时即终止,不重试(S7)
        except OpenAIError:
            return _error(502, "MODEL_UNPARSABLE", MSG_MODEL_UNPARSABLE)  # T7 兜底

        logger.info("recognize raw output: %r", raw)  # 模型原始输出留档(S3)
        level = normalize(raw)
        if level is not None:
            return JSONResponse(content={"level": level})

    return _error(502, "MODEL_UNPARSABLE", MSG_MODEL_UNPARSABLE)
