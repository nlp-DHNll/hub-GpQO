# app/main.py

import asyncio
import logging
import os
import tempfile

from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    UploadFile,
)

from app.config import (
    MODEL_PATH,
    MAX_UPLOAD_SIZE_BYTES,
    ALLOWED_CONTENT_TYPES,
)

from app.model_service import FireSafetyModel

from app.schemas import (
    RiskRecognitionResponse,
)


# 日志配置
logging.basicConfig(
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 生命周期管理。

    应用启动时加载一次模型；
    应用运行期间复用该模型；
    应用关闭时释放应用持有的模型引用。
    """

    logger.info("正在初始化消防风险识别服务")

    # 只在服务启动时加载模型一次
    app.state.fire_model = FireSafetyModel(
        model_path=MODEL_PATH
    )

    logger.info("消防风险识别服务初始化完成")

    try:
        yield

    finally:
        # 释放应用持有的引用
        app.state.fire_model = None

        logger.info("消防风险识别服务已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="楼道消防安全风险识别 API",
    description="基于 Qwen3-VL 的楼道消防风险识别服务",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """
    基础服务存活检查。
    """

    return {
        "status": "ok"
    }


@app.post(
    "/api/v1/fire-risk",
    response_model=RiskRecognitionResponse,
    summary="楼道消防风险识别",
)
async def identify_fire_risk(
    file: UploadFile = File(...),
):
    """
    上传楼道图片并识别消防风险。

    请求方式：
        POST /api/v1/fire-risk

    请求类型：
        multipart/form-data

    文件字段：
        file
    """

    # 检查上传的 MIME 类型
    if file.content_type not in ALLOWED_CONTENT_TYPES:

        raise HTTPException(
            status_code=415,
            detail=(
                "不支持的图片类型，"
                "请上传 JPEG、PNG 或 WEBP 图片"
            ),
        )

    # MIME 类型与临时文件后缀映射
    suffix_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    temp_path = None

    try:
        # 限制读取的数据量
        content = await file.read(
            MAX_UPLOAD_SIZE_BYTES + 1
        )

        if not content:

            raise HTTPException(
                status_code=400,
                detail="上传的图片为空",
            )

        if len(content) > MAX_UPLOAD_SIZE_BYTES:

            raise HTTPException(
                status_code=413,
                detail="上传图片超过大小限制",
            )

        # 创建临时文件
        # 不使用客户端提供的文件名，避免路径问题
        with tempfile.NamedTemporaryFile(
            suffix=suffix_map[file.content_type],
            delete=False,
        ) as temp_file:

            temp_file.write(content)

            temp_path = temp_file.name

        # 获取已初始化的模型实例
        model: FireSafetyModel = (
            app.state.fire_model
        )

        # 在工作线程中执行同步推理，避免直接阻塞事件循环
        result = await asyncio.to_thread(
            model.predict,
            temp_path,
        )

        # 返回标准化 JSON
        return {
            "success": True,
            "data": result,
        }

    except HTTPException:
        # 保留明确的 HTTP 错误状态码
        raise

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception:

        logger.exception(
            "楼道消防风险识别接口执行失败"
        )

        raise HTTPException(
            status_code=500,
            detail="服务器处理请求失败",
        ) from None

    finally:

        # 清理临时文件
        if (
            temp_path
            and os.path.exists(temp_path)
        ):

            try:
                os.remove(temp_path)

            except OSError:

                logger.warning(
                    "临时文件清理失败：%s",
                    temp_path,
                )

        # 关闭上传文件对象
        await file.close()