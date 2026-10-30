"""运行配置：视觉模型相关参数只从环境变量读取，避免把密钥写进代码。

支持的模型（OpenAI 兼容的视觉接口）：
- 通义千问视觉：   VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
                   VISION_MODEL=qwen-vl-max-latest  (或 qwen2.5-vl-72b-instruct)
- DeepSeek 视觉：  VISION_BASE_URL=你的兼容网关
                   VISION_MODEL=deepseek-vision-xxx
- 本地/自建：      VISION_BASE_URL=http://localhost:8000/v1
                   VISION_MODEL=local-model
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # 视觉大模型
    api_key: str = os.getenv("VISION_API_KEY", "sk-xx")
    base_url: str = os.getenv(
        "VISION_BASE_URL", "https://maas.qianwenaiapi.com/compatible-mode/v1"
    )
    model: str = os.getenv("VISION_MODEL", "qwen3.8-flash")
    temperature: float = float(os.getenv("VISION_TEMPERATURE", "0"))
    max_tokens: int = int(os.getenv("VISION_MAX_TOKENS", "1024"))

    # 服务
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    # 允许的最大上传体积（字节），默认 10MB
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))


settings = Settings()
